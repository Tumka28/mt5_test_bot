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
//|  Энэ файл одоогоор skeleton — алхам алхмаар бөглөнө.              |
//|  Build хийхээс өмнө терминалын Tools→Options→Expert Advisors-д    |
//|  "Allow DLL imports" асаасан байх ёстой.                          |
//+------------------------------------------------------------------+
#property copyright "MT5 Test Bot"
#property version   "0.1"
#property strict

input string  PubAddress           = "tcp://127.0.0.1:5555";
input string  RpcAddress           = "tcp://127.0.0.1:5556";
input int     HeartbeatSeconds     = 5;
input int     FlattenOnSilenceS    = 60;
input bool    AllowExecution       = false;   // false бол зөвхөн published, no orders

datetime g_last_heartbeat_in = 0;

int OnInit()
  {
   Print("bridge_ea init  pub=", PubAddress, " rpc=", RpcAddress);
   // TODO: zmq_ctx_new(), zmq_socket(ZMQ_PUB), zmq_bind(PubAddress)
   // TODO: zmq_socket(ZMQ_REP), zmq_bind(RpcAddress)
   EventSetTimer(1);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   // TODO: close sockets, zmq_ctx_term
  }

void OnTick()
  {
   // TODO: pull SymbolInfoTick, msgpack-encode, hmac-sign, zmq_send PUB
   // payload: {type:"tick", symbol, bid, ask, ts_ms, volume}
  }

void OnTimer()
  {
   // TODO: PUB heartbeat every HeartbeatSeconds
   // TODO: poll RPC socket non-blocking; if order msg arrives, ExecuteOrder()
   // TODO: if (TimeCurrent() - g_last_heartbeat_in) > FlattenOnSilenceS → FlattenAll()
  }

void ExecuteOrder(const string &payload_json)
  {
   if(!AllowExecution)
     {
      Print("execution disabled — would have run: ", payload_json);
      return;
     }
   // TODO: parse payload, build MqlTradeRequest, OrderSend(), send fill back via RPC reply
  }

void FlattenAll()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      // TODO: build close request and OrderSend()
     }
  }
//+------------------------------------------------------------------+
