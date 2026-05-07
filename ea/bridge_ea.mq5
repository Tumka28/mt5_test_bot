//+------------------------------------------------------------------+
//|                                                  bridge_ea.mq5   |
//|                    MT5 Test Bot — native socket bridge (no DLL)  |
//+------------------------------------------------------------------+
//|                                                                  |
//|  MT5-ийн native Socket API ашиглана. DLL-гүй, гуравдагч этгээд-   |
//|  гүй. EA нь TCP CLIENT, Python brain TCP SERVER.                  |
//|                                                                  |
//|  Wire format: line-based (\n delimiter), pipe-separated:          |
//|    EA → brain:                                                    |
//|      tick|symbol=...|bid=...|ask=...|ts_ms=...|volume=...         |
//|      heartbeat|ts_ms=...|source=gateway                           |
//|      account|equity=...|balance=...|currency=USD|ts_ms=...        |
//|      position|ticket=...|symbol=...|side=buy/sell|lots=...|       |
//|               entry=...|sl=...|tp=...|open_ts_ms=...              |
//|      ok|ticket=...|price=...|client_id=...                        |
//|      err|reason=...|client_id=...                                 |
//|    brain → EA:                                                    |
//|      order|client_id=...|symbol=...|side=...|lots=...|sl=...|tp=. |
//|      flatten_all                                                  |
//|      ping                                                         |
//|                                                                  |
//|  Setup:                                                           |
//|    1. Tools → Options → Expert Advisors:                          |
//|       ☑ Allow algorithmic trading                                 |
//|       ☑ Allow WebRequest for listed URL                           |
//|         + http://127.0.0.1:5555                                   |
//|    2. Toolbar дээр "Algo Trading" товч асаах                      |
//+------------------------------------------------------------------+
#property copyright "MT5 Test Bot"
#property version   "1.10"
#property strict

#include <Trade/Trade.mqh>

input string  Host                 = "127.0.0.1";
input int     Port                 = 5555;
input int     HeartbeatSeconds     = 5;
input int     AccountPushSeconds   = 5;       // account info refresh
input int     PositionsPushSeconds = 3;       // positions snapshot refresh
input int     ReconnectSeconds     = 3;
input int     FlattenOnSilenceS    = 60;
input bool    AllowExecution       = false;   // false = dry run; true = LIVE!
input string  HelloToken           = "";      // optional shared token; brain l mednE

CTrade   g_trade;
int      g_sock                   = INVALID_HANDLE;
datetime g_last_heartbeat_sent    = 0;
datetime g_last_account_sent      = 0;
datetime g_last_positions_sent    = 0;
datetime g_last_brain_msg_time    = 0;
datetime g_last_reconnect_attempt = 0;
string   g_recv_buffer            = "";
double   g_day_start_balance      = 0.0;
datetime g_day_start_date         = 0;

//+------------------------------------------------------------------+
//| Determine account_type — demo/real/contest. Forward-declared so   |
//| ConnectBrain()-аас дуудаж болно.                                  |
//+------------------------------------------------------------------+
string AccountTypeStr()
{
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_DEMO)    return "demo";
   if(mode == ACCOUNT_TRADE_MODE_CONTEST) return "contest";
   if(mode == ACCOUNT_TRADE_MODE_REAL)    return "real";
   return "unknown";
}

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
   // Send a "hello" line first so brain knows account info immediately.
   string hello = StringFormat(
      "hello|account_type=%s|login=%I64d|server=%s|build=%d|token=%s",
      AccountTypeStr(),
      AccountInfoInteger(ACCOUNT_LOGIN),
      AccountInfoString(ACCOUNT_SERVER),
      (int)TerminalInfoInteger(TERMINAL_BUILD),
      HelloToken);
   SendLine(hello);
   return true;
}

//+------------------------------------------------------------------+
bool SendLine(const string body)
{
   if(g_sock == INVALID_HANDLE) return false;
   string line = body + "\n";
   uchar bytes[];
   int n = StringToCharArray(line, bytes, 0, StringLen(line), CP_UTF8);
   if(n <= 0) return false;
   uint sent = SocketSend(g_sock, bytes, n - 1);
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

   int nl = StringFind(g_recv_buffer, "\n");
   while(nl >= 0)
   {
      string line = StringSubstr(g_recv_buffer, 0, nl);
      g_recv_buffer = StringSubstr(g_recv_buffer, nl + 1);
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
string HandleLine(const string line)
{
   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 1) return "err|reason=empty";
   string mtype = parts[0];
   if(mtype == "order")        return ExecuteOrder(parts);
   if(mtype == "modify")       return ModifyPosition(parts);
   if(mtype == "flatten_all")  { FlattenAll(); return "ok|action=flatten"; }
   if(mtype == "kill_all")     { FlattenAll(); return "ok|action=kill"; }
   if(mtype == "ping")         return "ok|pong=1";
   if(mtype == "draw_zone")    return DrawZone(parts);
   if(mtype == "draw_line")    return DrawLine(parts);
   if(mtype == "draw_label")   return DrawLabel(parts);
   if(mtype == "draw_arrow")   return DrawArrow(parts);
   if(mtype == "draw_path")    return DrawPath(parts);
   if(mtype == "clear")        return ClearByPrefix(parts);
   if(mtype == "get_bars")     return SendBars(parts);
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
//| Modify position SL/TP — brain-аас trail хийдэг                    |
//+------------------------------------------------------------------+
string ModifyPosition(const string &parts[])
{
   ulong ticket = (ulong)StringToInteger(GetField(parts, "ticket"));
   double sl    = StringToDouble(GetField(parts, "sl"));
   double tp    = StringToDouble(GetField(parts, "tp"));
   if(!AllowExecution)
      return StringFormat("ok|dry_run=1|ticket=%I64u", ticket);
   if(!PositionSelectByTicket(ticket))
      return StringFormat("err|reason=position_not_found|ticket=%I64u", ticket);
   bool ok = g_trade.PositionModify(ticket, sl, tp);
   if(!ok) return StringFormat("err|reason=modify_failed|retcode=%d|ticket=%I64u",
                               g_trade.ResultRetcode(), ticket);
   return StringFormat("ok|action=modify|ticket=%I64u|sl=%.5f|tp=%.5f", ticket, sl, tp);
}

//+------------------------------------------------------------------+
//|             ─── chart drawing primitives ───                      |
//| Бүх объектын name brain-аас өгсөн тогтмол ID байх ёстой —         |
//| ижил нэртэй object-ыг update хийнэ (delete + create).             |
//+------------------------------------------------------------------+
color ParseColor(const string raw, const color fallback)
{
   if(StringLen(raw) == 0) return fallback;
   long v = StringToInteger(raw);
   return (color)v;
}

void RecreateObject(const string name, const ENUM_OBJECT type)
{
   if(ObjectFind(0, name) >= 0)
      ObjectDelete(0, name);
   // Caller will ObjectCreate next.
}

string DrawZone(const string &parts[])
{
   string name  = GetField(parts, "name");
   long t1_ms   = StringToInteger(GetField(parts, "t1"));
   double p1    = StringToDouble(GetField(parts, "p1"));
   long t2_ms   = StringToInteger(GetField(parts, "t2"));
   double p2    = StringToDouble(GetField(parts, "p2"));
   color clr    = ParseColor(GetField(parts, "color"), clrDodgerBlue);
   bool   fill  = (GetField(parts, "fill") == "1");
   int    width = (int)StringToInteger(GetField(parts, "width"));
   if(width <= 0) width = 1;
   if(StringLen(name) == 0) return "err|reason=name_required";
   datetime t1 = (datetime)(t1_ms / 1000);
   datetime t2 = (datetime)(t2_ms / 1000);
   RecreateObject(name, OBJ_RECTANGLE);
   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
      return StringFormat("err|reason=create_failed|err=%d|name=%s", GetLastError(), name);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_FILL, fill);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   return "ok|name=" + name;
}

string DrawLine(const string &parts[])
{
   string name = GetField(parts, "name");
   long t1_ms  = StringToInteger(GetField(parts, "t1"));
   double p1   = StringToDouble(GetField(parts, "p1"));
   long t2_ms  = StringToInteger(GetField(parts, "t2"));
   double p2   = StringToDouble(GetField(parts, "p2"));
   color clr   = ParseColor(GetField(parts, "color"), clrYellow);
   int    style= (int)StringToInteger(GetField(parts, "style"));   // 0=solid,2=dot,1=dash
   int    width= (int)StringToInteger(GetField(parts, "width"));
   if(width <= 0) width = 1;
   if(StringLen(name) == 0) return "err|reason=name_required";
   datetime t1 = (datetime)(t1_ms / 1000);
   datetime t2 = (datetime)(t2_ms / 1000);
   RecreateObject(name, OBJ_TREND);
   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2))
      return StringFormat("err|reason=create_failed|err=%d|name=%s", GetLastError(), name);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   return "ok|name=" + name;
}

string DrawLabel(const string &parts[])
{
   string name  = GetField(parts, "name");
   long t_ms    = StringToInteger(GetField(parts, "t"));
   double price = StringToDouble(GetField(parts, "p"));
   string text  = GetField(parts, "text");
   color clr    = ParseColor(GetField(parts, "color"), clrWhite);
   string font  = GetField(parts, "font"); if(StringLen(font) == 0) font = "Arial";
   int size     = (int)StringToInteger(GetField(parts, "size"));
   if(size <= 0) size = 9;
   if(StringLen(name) == 0) return "err|reason=name_required";
   StringReplace(text, "%20", " ");
   StringReplace(text, "%7C", "|");
   datetime t   = (datetime)(t_ms / 1000);
   RecreateObject(name, OBJ_TEXT);
   if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, price))
      return StringFormat("err|reason=create_failed|err=%d|name=%s", GetLastError(), name);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, font);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   return "ok|name=" + name;
}

string DrawArrow(const string &parts[])
{
   string name  = GetField(parts, "name");
   long t_ms    = StringToInteger(GetField(parts, "t"));
   double price = StringToDouble(GetField(parts, "p"));
   string side  = GetField(parts, "side");
   color clr    = ParseColor(GetField(parts, "color"), clrAqua);
   if(StringLen(name) == 0) return "err|reason=name_required";
   datetime t   = (datetime)(t_ms / 1000);
   ENUM_OBJECT obj_type = (side == "up") ? OBJ_ARROW_UP : OBJ_ARROW_DOWN;
   RecreateObject(name, obj_type);
   if(!ObjectCreate(0, name, obj_type, 0, t, price))
      return StringFormat("err|reason=create_failed|err=%d|name=%s", GetLastError(), name);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 3);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   return "ok|name=" + name;
}

//+------------------------------------------------------------------+
//| Multi-segment projection path. points field formatted:            |
//|   t1,p1;t2,p2;t3,p3;...                                           |
//| name-base дотор segment index-аар нэр өгнө: name_0, name_1, ...   |
//+------------------------------------------------------------------+
string DrawPath(const string &parts[])
{
   string name  = GetField(parts, "name");
   string raw   = GetField(parts, "points");
   color clr    = ParseColor(GetField(parts, "color"), clrAqua);
   int style    = (int)StringToInteger(GetField(parts, "style"));
   int width    = (int)StringToInteger(GetField(parts, "width"));
   if(width <= 0) width = 2;
   if(StringLen(name) == 0 || StringLen(raw) == 0) return "err|reason=missing_args";

   string segs[];
   int n = StringSplit(raw, ';', segs);
   if(n < 2) return "err|reason=need_at_least_2_points";

   // Cleanup any previous segments belonging to this path
   string prev_prefix = name + "_seg_";
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string objn = ObjectName(0, i);
      if(StringFind(objn, prev_prefix) == 0)
         ObjectDelete(0, objn);
   }

   long   prev_t = 0;
   double prev_p = 0.0;
   bool   first  = true;
   int seg_idx = 0;
   for(int i = 0; i < n; i++)
   {
      string pair[];
      if(StringSplit(segs[i], ',', pair) < 2) continue;
      long   ti = StringToInteger(pair[0]);
      double pi = StringToDouble(pair[1]);
      if(!first)
      {
         string seg_name = StringFormat("%s%d", prev_prefix, seg_idx++);
         datetime t1 = (datetime)(prev_t / 1000);
         datetime t2 = (datetime)(ti / 1000);
         if(ObjectCreate(0, seg_name, OBJ_TREND, 0, t1, prev_p, t2, pi))
         {
            ObjectSetInteger(0, seg_name, OBJPROP_COLOR, clr);
            ObjectSetInteger(0, seg_name, OBJPROP_STYLE, style);
            ObjectSetInteger(0, seg_name, OBJPROP_WIDTH, width);
            ObjectSetInteger(0, seg_name, OBJPROP_RAY_RIGHT, false);
            ObjectSetInteger(0, seg_name, OBJPROP_SELECTABLE, false);
         }
      }
      prev_t = ti; prev_p = pi; first = false;
   }
   return StringFormat("ok|name=%s|segments=%d", name, seg_idx);
}

//+------------------------------------------------------------------+
//| Delete all objects whose name starts with `prefix`.               |
//+------------------------------------------------------------------+
string ClearByPrefix(const string &parts[])
{
   string prefix = GetField(parts, "prefix");
   if(StringLen(prefix) == 0) return "err|reason=prefix_required";
   int removed = 0;
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string objn = ObjectName(0, i);
      if(StringFind(objn, prefix) == 0)
      {
         ObjectDelete(0, objn);
         removed++;
      }
   }
   return StringFormat("ok|cleared=%d", removed);
}

//+------------------------------------------------------------------+
//| Send N bars of OHLC history. Reply format:                        |
//|   bars|req_id=...|symbol=...|tf=...|count=...|data=t,o,h,l,c,v;...|
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TimeframeFromString(const string s)
{
   if(s == "M1")  return PERIOD_M1;
   if(s == "M5")  return PERIOD_M5;
   if(s == "M15") return PERIOD_M15;
   if(s == "M30") return PERIOD_M30;
   if(s == "H1")  return PERIOD_H1;
   if(s == "H4")  return PERIOD_H4;
   if(s == "D1")  return PERIOD_D1;
   if(s == "W1")  return PERIOD_W1;
   if(s == "MN1") return PERIOD_MN1;
   return PERIOD_M5;
}

string SendBars(const string &parts[])
{
   string symbol  = GetField(parts, "symbol");
   string tf_str  = GetField(parts, "tf");
   int count      = (int)StringToInteger(GetField(parts, "count"));
   string req_id  = GetField(parts, "req_id");
   if(count <= 0) count = 200;
   if(count > 5000) count = 5000;
   ENUM_TIMEFRAMES tf = TimeframeFromString(tf_str);
   MqlRates rates[];
   int got = CopyRates(symbol, tf, 0, count, rates);
   if(got <= 0)
      return StringFormat("err|reason=copy_rates_failed|err=%d|req_id=%s", GetLastError(), req_id);
   string buf = "";
   for(int i = 0; i < got; i++)
   {
      long t_ms = (long)rates[i].time * 1000;
      buf += StringFormat("%I64d,%.5f,%.5f,%.5f,%.5f,%I64d",
                          t_ms, rates[i].open, rates[i].high,
                          rates[i].low, rates[i].close, (long)rates[i].tick_volume);
      if(i < got - 1) buf += ";";
   }
   return StringFormat("bars|req_id=%s|symbol=%s|tf=%s|count=%d|data=%s",
                       req_id, symbol, tf_str, got, buf);
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
//| Push current account state to brain.                              |
//+------------------------------------------------------------------+
void PushAccount()
{
   datetime today = StringToTime(TimeToString(TimeCurrent(), TIME_DATE));
   if(today != g_day_start_date)
   {
      g_day_start_date     = today;
      g_day_start_balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   }
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double pnl_today = balance - g_day_start_balance;
   string ccy = AccountInfoString(ACCOUNT_CURRENCY);
   string acct_type = AccountTypeStr();
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   string server = AccountInfoString(ACCOUNT_SERVER);
   long ts_ms = (long)TimeCurrent() * 1000;
   string body = StringFormat(
      "account|equity=%.2f|balance=%.2f|currency=%s|pnl_today=%.2f|account_type=%s|login=%I64d|server=%s|ts_ms=%I64d",
      equity, balance, ccy, pnl_today, acct_type, login, server, ts_ms);
   SendLine(body);
}

//+------------------------------------------------------------------+
//| Push all open positions (one line each).                          |
//+------------------------------------------------------------------+
void PushPositions()
{
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      string symbol = (string)PositionGetString(POSITION_SYMBOL);
      long type     = (long)PositionGetInteger(POSITION_TYPE);
      string side   = (type == POSITION_TYPE_BUY) ? "buy" : "sell";
      double lots   = PositionGetDouble(POSITION_VOLUME);
      double entry  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl     = PositionGetDouble(POSITION_SL);
      double tp     = PositionGetDouble(POSITION_TP);
      long open_ts  = (long)PositionGetInteger(POSITION_TIME) * 1000;
      string body = StringFormat(
         "position|ticket=%I64u|symbol=%s|side=%s|lots=%.2f|entry=%.5f|sl=%.5f|tp=%.5f|open_ts_ms=%I64d",
         ticket, symbol, side, lots, entry, sl, tp, open_ts);
      SendLine(body);
   }
   // Sentinel so brain knows snapshot is complete (even when zero positions)
   long ts_ms = (long)TimeCurrent() * 1000;
   string body = StringFormat("positions_end|count=%d|ts_ms=%I64d", total, ts_ms);
   SendLine(body);
}

//+------------------------------------------------------------------+
int OnInit()
{
   ConnectBrain();
   EventSetTimer(1);
   PrintFormat("bridge_ea up  host=%s port=%d exec=%s", Host, Port, (string)AllowExecution);
   if(AllowExecution)
      Print("⚠️  ANHAARAH: AllowExecution=TRUE — REAL ORDERS DAMJUUNA");
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

   if(g_sock == INVALID_HANDLE)
   {
      if(now - g_last_reconnect_attempt >= ReconnectSeconds)
      {
         g_last_reconnect_attempt = now;
         ConnectBrain();
      }
      return;
   }

   DrainSocket();

   if(now - g_last_heartbeat_sent >= HeartbeatSeconds)
   {
      string body = StringFormat("heartbeat|ts_ms=%I64d|source=gateway",
                                 (long)now * 1000);
      SendLine(body);
      g_last_heartbeat_sent = now;
   }

   if(now - g_last_account_sent >= AccountPushSeconds)
   {
      PushAccount();
      g_last_account_sent = now;
   }

   if(now - g_last_positions_sent >= PositionsPushSeconds)
   {
      PushPositions();
      g_last_positions_sent = now;
   }

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
