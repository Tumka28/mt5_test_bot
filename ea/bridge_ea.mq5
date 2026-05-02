//+------------------------------------------------------------------+
//|                                                  bridge_ea.mq5   |
//|                              MT5 Test Bot — thin execution EA    |
//+------------------------------------------------------------------+
//|                                                                  |
//|  Энэ EA-д ШИЙДВЭР ГАРГАХ ЛОГИК БАЙХГҮЙ.                           |
//|  Бүх индикатор, signal, sizing — Python brain-д.                 |
//|                                                                  |
//|  Үүрэг:                                                           |
//|  1) ZMQ-аар Python руу tick + heartbeat явуулах (libzmq.dll)      |
//|  2) Python-аас irsen orders-ыг гүйцэтгэх                          |
//|  3) Python-аас heartbeat алдагдсан үед бүх позицийг хаах          |
//|                                                                  |
//|  Build:                                                           |
//|    1. mql-zmq (https://github.com/dingmaotu/mql-zmq) суулга:      |
//|       Include/Zmq, Library/Zmq.dll  →  MT5 data folder            |
//|    2. Tools → Options → Expert Advisors:                          |
//|         ☑ Allow algorithmic trading                               |
//|         ☑ Allow DLL imports                                       |
//|    3. F7 to compile.                                              |
//|                                                                  |
//|  Wire format (Python-тай адил):                                  |
//|    JSON-ийн оронд эхлэхдээ зөвхөн PIPE-delimited string ашиглана  |
//|    учир нь msgpack-ийг MQL5-д бичих нь хэт нийтлэг биш.           |
//|    Format: "type|key1=val1|key2=val2|..."                         |
//|    Жишээ: "tick|symbol=EURUSD|bid=1.10412|ask=1.10421|ts=170..."  |
//|    HMAC-SHA256-ийг мөн bytes-ээр prepend хийнэ.                  |
//|                                                                  |
//|  ⚠ JSON/msgpack дэмжлэг нэмэхийн тулд хожим обновить — одоохондоо |
//|    Python тал нэмэлт parser-тэй (bridge/transport.py-аас өөр код  |
//|    хэрэгтэй, эсвэл MQL5-д msgpack DLL импортлох).                |
//+------------------------------------------------------------------+
#property copyright "MT5 Test Bot"
#property version   "0.2"
#property strict

#include <Zmq/Zmq.mqh>
#include <Trade/Trade.mqh>

input string  PubAddress           = "tcp://127.0.0.1:5555";
input string  RpcAddress           = "tcp://127.0.0.1:5556";
input int     HeartbeatSeconds     = 5;
input int     FlattenOnSilenceS    = 60;
input bool    AllowExecution       = false;   // false = dry run, no orders
input string  HmacSecret           = "dev-only-change-me";

Context  *g_ctx       = NULL;
Socket   *g_pub       = NULL;
Socket   *g_rpc       = NULL;
CTrade    g_trade;

datetime g_last_brain_msg_time = 0;
datetime g_last_heartbeat_sent = 0;

//+------------------------------------------------------------------+
//| Hex SHA256 — used for HMAC. Trivial wrapper around CryptEncode.  |
//+------------------------------------------------------------------+
string ComputeHmacHex(const string secret, const string body)
{
   uchar key[];   StringToCharArray(secret, key, 0, StringLen(secret));
   uchar data[];  StringToCharArray(body, data, 0, StringLen(body));
   uchar hash[];
   if(!CryptEncode(CRYPT_HASH_SHA256, data, key, hash))
      return "";
   string hex = "";
   for(int i = 0; i < ArraySize(hash); i++)
      hex += StringFormat("%02x", hash[i]);
   return hex;
}

//+------------------------------------------------------------------+
//| Pipe-delimited message builder.                                   |
//| Returns body with HMAC prepended as "<hex>|<body>".               |
//+------------------------------------------------------------------+
string SignedFrame(const string body)
{
   string sig = ComputeHmacHex(HmacSecret, body);
   return sig + "|" + body;
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_ctx = new Context("bridge_ea");
   g_pub = new Socket(g_ctx, ZMQ_PUB);
   if(!g_pub.bind(PubAddress)) {
      Print("PUB bind failed: ", PubAddress); return INIT_FAILED;
   }
   g_rpc = new Socket(g_ctx, ZMQ_REP);
   if(!g_rpc.bind(RpcAddress)) {
      Print("RPC bind failed: ", RpcAddress); return INIT_FAILED;
   }
   g_rpc.setLinger(0);
   g_pub.setLinger(0);
   g_last_brain_msg_time = TimeCurrent();
   EventSetTimer(1);
   PrintFormat("bridge_ea up  pub=%s rpc=%s exec=%s",
               PubAddress, RpcAddress, (string)AllowExecution);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_pub) { delete g_pub; g_pub = NULL; }
   if(g_rpc) { delete g_rpc; g_rpc = NULL; }
   if(g_ctx) { delete g_ctx; g_ctx = NULL; }
}

//+------------------------------------------------------------------+
void OnTick()
{
   string sym = _Symbol;
   MqlTick t;
   if(!SymbolInfoTick(sym, t)) return;

   long ts_ms = (long)(t.time_msc);
   string body = StringFormat(
      "tick|symbol=%s|bid=%.5f|ask=%.5f|ts_ms=%I64d|volume=%I64d",
      sym, t.bid, t.ask, ts_ms, (long)t.volume);

   ZmqMsg msg(SignedFrame(body));
   g_pub.send(msg, true);   // true = non-blocking
}

//+------------------------------------------------------------------+
void OnTimer()
{
   datetime now = TimeCurrent();

   // 1. Heartbeat
   if(now - g_last_heartbeat_sent >= HeartbeatSeconds)
   {
      string body = StringFormat("heartbeat|ts_ms=%I64d|source=gateway",
                                 (long)now * 1000);
      ZmqMsg hb(SignedFrame(body));
      g_pub.send(hb, true);
      g_last_heartbeat_sent = now;
   }

   // 2. Drain RPC requests (orders)
   ZmqMsg req;
   while(g_rpc.recv(req, true))   // non-blocking
   {
      string raw = req.getData();
      g_last_brain_msg_time = now;
      string reply = HandleRpc(raw);
      ZmqMsg rep(reply);
      g_rpc.send(rep, true);
   }

   // 3. Heartbeat-loss watchdog
   if(now - g_last_brain_msg_time > FlattenOnSilenceS)
   {
      static datetime last_log = 0;
      if(now - last_log > 30) {
         Print("WATCHDOG: brain silent ", now - g_last_brain_msg_time, "s — flattening");
         last_log = now;
      }
      FlattenAll();
   }
}

//+------------------------------------------------------------------+
//| Parse "<sig>|<body>", verify HMAC, dispatch.                     |
//| Reply format: "ok|key=val|..." or "err|reason=..."                |
//+------------------------------------------------------------------+
string HandleRpc(const string raw)
{
   int sep = StringFind(raw, "|");
   if(sep < 0) return "err|reason=malformed";
   string sig  = StringSubstr(raw, 0, sep);
   string body = StringSubstr(raw, sep + 1);
   if(ComputeHmacHex(HmacSecret, body) != sig)
      return "err|reason=hmac";

   // body format: "type|k=v|..."  e.g. "order|client_id=...|symbol=EURUSD|side=buy|lots=0.10|sl=1.0950|tp=1.1100|entry=1.1000"
   string parts[];
   int n = StringSplit(body, '|', parts);
   if(n < 1) return "err|reason=empty";
   string mtype = parts[0];

   if(mtype == "order")        return ExecuteOrder(parts);
   if(mtype == "flatten_all")  { FlattenAll(); return "ok|action=flatten"; }
   if(mtype == "ping")         return "ok|pong=1";
   return "err|reason=unknown_type";
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
   // entry хадгалагдаагүй — market order гэж тооцно

   if(!AllowExecution)
   {
      PrintFormat("DRY RUN: would execute %s %s %.2f sl=%.5f tp=%.5f id=%s",
                  side, symbol, lots, sl, tp, client_id);
      return "ok|dry_run=1|client_id=" + client_id;
   }

   bool ok = false;
   if(side == "buy")       ok = g_trade.Buy(lots, symbol, 0, sl, tp, client_id);
   else if(side == "sell") ok = g_trade.Sell(lots, symbol, 0, sl, tp, client_id);
   else return "err|reason=bad_side";

   if(!ok) return StringFormat("err|reason=trade_failed|retcode=%d",
                               g_trade.ResultRetcode());

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
