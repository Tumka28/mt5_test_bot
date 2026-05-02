//+------------------------------------------------------------------+
//|                                                  bridge_ea.mq5   |
//|                    MT5 Test Bot — native socket bridge (no DLL)  |
//+------------------------------------------------------------------+
//|                                                                  |
//|  MT5-ийн native Socket API ашиглана (build 2340+). DLL хэрэггүй,  |
//|  mql-zmq хэрэггүй. EA нь TCP CLIENT, Python brain TCP SERVER.    |
//|                                                                  |
//|  Wire format: line-based (\n delimiter), text only:               |
//|    out (EA → brain):                                              |
//|      tick|symbol=EURUSD|bid=1.10412|ask=1.10421|ts_ms=...         |
//|      heartbeat|ts_ms=...|source=gateway                           |
//|    in  (brain → EA):                                              |
//|      order|client_id=...|symbol=EURUSD|side=buy|lots=0.10|        |
//|              sl=1.0950|tp=1.1100|entry=1.1000                     |
//|      flatten_all                                                  |
//|      ping                                                         |
//|    EA reply бүрт line:                                            |
//|      ok|ticket=...|price=...                                      |
//|      err|reason=...                                               |
//|                                                                  |
//|  HMAC-ийг simple авч хассан (loopback only). Шаардлагатай бол     |
//|  string-н prefix-ээр нэмж болно.                                  |
//|                                                                  |
//|  Setup:                                                           |
//|    1. Tools → Options → Expert Advisors:                          |
//|       ☑ Allow algorithmic trading                                 |
//|       ☑ Allow WebRequest for the following URLs:                  |
//|          (URL биш, чөлөөтэй TCP — энэ check шаардахгүй)           |
//|    2. (Энэ EA-д DLL imports check хэрэггүй!)                      |
//|    3. F7 to compile.                                              |
//+------------------------------------------------------------------+
#property copyright "MT5 Test Bot"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input string  Host                = "127.0.0.1";
input int     Port                = 5555;
input int     HeartbeatSeconds    = 5;
input int     ReconnectSeconds    = 3;
input int     FlattenOnSilenceS   = 60;
input bool    AllowExecution      = false;     // false = dry run

CTrade   g_trade;
int      g_sock                   = INVALID_HANDLE;
datetime g_last_heartbeat_sent    = 0;
datetime g_last_brain_msg_time    = 0;
datetime g_last_reconnect_attempt = 0;
string   g_recv_buffer            = "";

//+------------------------------------------------------------------+
//| Connect (or reconnect) to brain.                                 |
//+------------------------------------------------------------------+
bool ConnectBrain()
{
   if(g_sock != INVALID_HANDLE)
   {
      SocketClose(g_sock);
      g_sock = INVALID_HANDLE;
   }
   g_sock = SocketCreate();
   if(g_sock == INVALID_HANDLE)
   {
      PrintFormat("SocketCreate failed: err=%d", GetLastError());
      return false;
   }
   if(!SocketConnect(g_sock, Host, Port, 1000))
   {
      PrintFormat("SocketConnect %s:%d failed: err=%d", Host, Port, GetLastError());
      SocketClose(g_sock);
      g_sock = INVALID_HANDLE;
      return false;
   }
   g_last_brain_msg_time = TimeCurrent();
   PrintFormat("connected to brain at %s:%d", Host, Port);
   return true;
}

//+------------------------------------------------------------------+
//| Send a single line (\n appended). Non-blocking-friendly.         |
//+------------------------------------------------------------------+
bool SendLine(const string body)
{
   if(g_sock == INVALID_HANDLE) return false;
   string line = body + "\n";
   uchar bytes[];
   int n = StringToCharArray(line, bytes, 0, StringLen(line), CP_UTF8);
   if(n <= 0) return false;
   uint sent = SocketSend(g_sock, bytes, n - 1);  // -1 to drop NUL terminator
   if(sent == 0)
   {
      PrintFormat("SocketSend failed: err=%d", GetLastError());
      SocketClose(g_sock);
      g_sock = INVALID_HANDLE;
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Drain socket into g_recv_buffer; return any complete lines.      |
//+------------------------------------------------------------------+
void DrainSocket()
{
   if(g_sock == INVALID_HANDLE) return;
   uint avail = SocketIsReadable(g_sock);
   while(avail > 0)
   {
      uchar buf[];
      int got = SocketRead(g_sock, buf, avail, 50);
      if(got <= 0) break;
      string chunk = CharArrayToString(buf, 0, got, CP_UTF8);
      g_recv_buffer += chunk;
      avail = SocketIsReadable(g_sock);
   }

   // Process all complete lines
   int nl = StringFind(g_recv_buffer, "\n");
   while(nl >= 0)
   {
      string line = StringSubstr(g_recv_buffer, 0, nl);
      g_recv_buffer = StringSubstr(g_recv_buffer, nl + 1);
      // strip trailing \r
      if(StringLen(line) > 0 && StringGetCharacter(line, StringLen(line) - 1) == 13)
         line = StringSubstr(line, 0, StringLen(line) - 1);
      if(StringLen(line) > 0)
      {
         g_last_brain_msg_time = TimeCurrent();
         string reply = HandleLine(line);
         if(StringLen(reply) > 0)
            SendLine(reply);
      }
      nl = StringFind(g_recv_buffer, "\n");
   }
}

//+------------------------------------------------------------------+
//| Parse "type|k=v|..." line.                                       |
//+------------------------------------------------------------------+
string HandleLine(const string line)
{
   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 1) return "err|reason=empty";
   string mtype = parts[0];
   if(mtype == "order")        return ExecuteOrder(parts);
   if(mtype == "flatten_all")  { FlattenAll(); return "ok|action=flatten"; }
   if(mtype == "ping")         return "ok|pong=1";
   return "err|reason=unknown_type:" + mtype;
}

//+------------------------------------------------------------------+
string GetField(const string &parts[], const string key)
{
   for(int i = 1; i < ArraySize(parts); i++)
   {
      int eq = StringFind(parts[i], "=");
      if(eq < 0) continue;
      if(StringSubstr(parts[i], 0, eq) == key)
         return StringSubstr(parts[i], eq + 1);
   }
   return "";
}

//+------------------------------------------------------------------+
string ExecuteOrder(const string &parts[])
{
   string client_id = GetField(parts, "client_id");
   string symbol    = GetField(parts, "symbol");
   string side      = GetField(parts, "side");
   double lots      = StringToDouble(GetField(parts, "lots"));
   double sl        = StringToDouble(GetField(parts, "sl"));
   double tp        = StringToDouble(GetField(parts, "tp"));

   if(!AllowExecution)
   {
      PrintFormat("DRY RUN: would execute %s %s %.2f sl=%.5f tp=%.5f id=%s",
                  side, symbol, lots, sl, tp, client_id);
      return "ok|dry_run=1|client_id=" + client_id;
   }

   bool ok = false;
   if(side == "buy")       ok = g_trade.Buy(lots, symbol, 0, sl, tp, client_id);
   else if(side == "sell") ok = g_trade.Sell(lots, symbol, 0, sl, tp, client_id);
   else return "err|reason=bad_side|client_id=" + client_id;

   if(!ok) return StringFormat("err|reason=trade_failed|retcode=%d|client_id=%s",
                               g_trade.ResultRetcode(), client_id);
   return StringFormat("ok|ticket=%I64u|price=%.5f|client_id=%s",
                       g_trade.ResultOrder(), g_trade.ResultPrice(), client_id);
}

//+------------------------------------------------------------------+
void FlattenAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      g_trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
int OnInit()
{
   ConnectBrain();   // best-effort; OnTimer will retry
   EventSetTimer(1);
   PrintFormat("bridge_ea up  host=%s port=%d exec=%s", Host, Port, (string)AllowExecution);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_sock != INVALID_HANDLE)
   {
      SocketClose(g_sock);
      g_sock = INVALID_HANDLE;
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(g_sock == INVALID_HANDLE) return;
   string sym = _Symbol;
   MqlTick t;
   if(!SymbolInfoTick(sym, t)) return;
   long ts_ms = (long)(t.time_msc);
   string body = StringFormat(
      "tick|symbol=%s|bid=%.5f|ask=%.5f|ts_ms=%I64d|volume=%I64d",
      sym, t.bid, t.ask, ts_ms, (long)t.volume);
   SendLine(body);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   datetime now = TimeCurrent();

   // 1. (Re)connect if disconnected
   if(g_sock == INVALID_HANDLE)
   {
      if(now - g_last_reconnect_attempt >= ReconnectSeconds)
      {
         g_last_reconnect_attempt = now;
         ConnectBrain();
      }
      return;
   }

   // 2. Drain & dispatch
   DrainSocket();

   // 3. Heartbeat
   if(now - g_last_heartbeat_sent >= HeartbeatSeconds)
   {
      string body = StringFormat("heartbeat|ts_ms=%I64d|source=gateway",
                                 (long)now * 1000);
      SendLine(body);
      g_last_heartbeat_sent = now;
   }

   // 4. Watchdog — flatten on prolonged brain silence
   if(now - g_last_brain_msg_time > FlattenOnSilenceS)
   {
      static datetime last_log = 0;
      if(now - last_log > 30) {
         PrintFormat("WATCHDOG: brain silent %ds — flattening", now - g_last_brain_msg_time);
         last_log = now;
      }
      FlattenAll();
   }
}
//+------------------------------------------------------------------+
