//+------------------------------------------------------------------+
//|                                         bridge_ea_skeleton.mq5   |
//|                                                                  |
//|  COMPILE-ONLY VARIANT.                                            |
//|  mql-zmq суулгахаас өмнө EA-ийн structure compile хийгдэж байгаа  |
//|  эсэхийг шалгахад хэрэглэнэ. ZMQ функцууд нь stub.                |
//|                                                                  |
//|  Бодит ажиллахын тулд `bridge_ea.mq5`-ыг ашигла.                  |
//+------------------------------------------------------------------+
#property copyright "MT5 Test Bot"
#property version   "0.2-skeleton"
#property strict

#include <Trade/Trade.mqh>

input string  PubAddress           = "tcp://127.0.0.1:5555";
input string  RpcAddress           = "tcp://127.0.0.1:5556";
input int     HeartbeatSeconds     = 5;
input int     FlattenOnSilenceS    = 60;
input bool    AllowExecution       = false;

CTrade g_trade;
datetime g_last_heartbeat_sent = 0;

int OnInit()
{
   PrintFormat("bridge_ea_skeleton up  pub=%s rpc=%s exec=%s",
               PubAddress, RpcAddress, (string)AllowExecution);
   EventSetTimer(1);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTick()
{
   string sym = _Symbol;
   MqlTick t;
   if(!SymbolInfoTick(sym, t)) return;
   // Skeleton: would PUB tick here via ZMQ
}

void OnTimer()
{
   datetime now = TimeCurrent();
   if(now - g_last_heartbeat_sent >= HeartbeatSeconds)
   {
      // Skeleton: would PUB heartbeat here
      g_last_heartbeat_sent = now;
   }
}

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
