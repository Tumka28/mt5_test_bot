//+------------------------------------------------------------------+
//|                                                  SmcVisualEA.mq5  |
//|                                                                    |
//|   ALL-IN-ONE Smart Money Concepts visualizer + optional trader.   |
//|   Python тал шаардахгүй: MetaEditor 5-д compile хийгээд chart-руу |
//|   drag хий — бүх SMC analysis, projection path, label-уудыг chart|
//|   дээр шууд зурна.                                                 |
//|                                                                    |
//|   Илрүүлдэг:                                                       |
//|     - Swing highs / lows  (Williams fractal)                       |
//|     - BOS  (Break of Structure) bull/bear                          |
//|     - CHOCH (Change of Character) bull/bear                        |
//|     - FVG  (Fair Value Gap) bull/bear, filled marker               |
//|     - OB   (Order Block) — last opposite candle before BOS         |
//|     - Liquidity zones (equal highs/lows clusters)                  |
//|                                                                    |
//|   Зурдаг:                                                          |
//|     - FVG, OB rectangles                                           |
//|     - BOS/CHOCH markers + labels                                   |
//|     - Bullish + bearish projection paths (multi-segment trend)     |
//|     - TP1 / TP2 / structure target / big target / invalidation     |
//|     - Telegram-format signal text in chart Comment()               |
//|                                                                    |
//|   Optional auto-trade:                                             |
//|     - InpAutoTrade = true үед probability >= threshold-той         |
//|       projection-аар buy/sell entry, SL = invalidation, TP=TP1     |
//|     - Risk manager: per-trade %, daily loss cap, max trades/day    |
//|                                                                    |
//|   Default-аар auto-trade унтраалттай — зөвхөн visualization.       |
//+------------------------------------------------------------------+
#property copyright "MT5 Test Bot — SMC Visual EA"
#property version   "1.00"
#property strict
#property description "All-in-one SMC analysis + projection drawing (optional auto-trade)"

#include <Trade\Trade.mqh>

//=== INPUTS =========================================================

input group "═══ Symbol / Timeframe ═══"
input string           InpSymbolOverride  = "";          // empty = current chart symbol
input ENUM_TIMEFRAMES  InpTimeframe       = PERIOD_CURRENT;
input int              InpBarsWindow      = 300;         // analysis lookback
input int              InpUpdateSeconds   = 5;           // re-analysis period

input group "═══ SMC Detection ═══"
input int     InpSwingLookback     = 2;     // Williams fractal pivots
input int     InpFvgMaxAge         = 100;   // ignore older FVGs (bars)
input int     InpObLookback        = 20;    // bars to walk back for OB
input double  InpLiqTolAtr         = 0.25;  // ATR fraction for liquidity cluster
input int     InpAtrPeriod         = 14;

input group "═══ Drawing toggles ═══"
input bool    InpDrawFvg           = true;
input bool    InpDrawOb            = true;
input bool    InpDrawEvents        = true;
input bool    InpDrawProjections   = true;
input bool    InpDrawTargets       = true;
input bool    InpShowComment       = true;
input int     InpMaxZonesDrawn     = 8;
input int     InpProjLookaheadBars = 12;

input group "═══ Colors (decimal MQL5) ═══"
input color   InpColorFvgBull      = clrDodgerBlue;
input color   InpColorFvgBear      = clrOrchid;
input color   InpColorObBull       = clrLimeGreen;
input color   InpColorObBear       = clrCrimson;
input color   InpColorBosBull      = clrLime;
input color   InpColorBosBear      = clrRed;
input color   InpColorPathBull     = clrAqua;
input color   InpColorPathBear     = clrOrange;
input color   InpColorTpLine       = clrWhite;
input color   InpColorInvalLine    = clrGray;

input group "═══ Optional auto-trade ═══"
input bool    InpAutoTrade         = false;       // ⚠ sеti tochirhuu uneer turshchirhah
input double  InpRiskPct           = 0.3;         // % equity per trade
input double  InpProbThreshold     = 0.68;        // min probability to trade
input double  InpMaxDailyLossPct   = 2.0;         // arm kill at this DD
input int     InpMaxTradesPerDay   = 3;
input int     InpMagic             = 778899;
input int     InpSlippagePoints    = 20;
input double  InpMinSeconds        = 60;          // min seconds between trades
input bool    InpUseStrucutreTarget= false;       // TP = structure target instead of TP1

//=== STATE ==========================================================

string   g_symbol;
ENUM_TIMEFRAMES g_tf;
CTrade   g_trade;

datetime g_day_start          = 0;
double   g_day_start_equity   = 0.0;
int      g_trades_today       = 0;
bool     g_kill_armed         = false;
datetime g_last_trade_time    = 0;
datetime g_last_analysis_time = 0;
string   g_prefix;            // object name prefix; "smc_<symbol>_<tf>_"

// Bar buffer (loaded each cycle)
MqlRates g_rates[];
int      g_bars_count = 0;

// SMC state
struct SwingPt
{
   int      idx;
   datetime ts;
   double   price;
   bool     is_high;
};
SwingPt g_swing_highs[];
SwingPt g_swing_lows[];

struct StructEv
{
   string   kind;       // "BOS" | "CHOCH"
   string   dir;        // "bull" | "bear"
   datetime ts;
   double   broken_price;
   datetime broken_ts;
   int      break_idx;
};
StructEv g_events[];
string   g_trend = "";   // "bull" | "bear" | ""

struct FvgZone
{
   string   dir;        // "bull" | "bear"
   datetime ts;
   double   top;
   double   bottom;
   bool     filled;
};
FvgZone g_fvgs[];

struct ObZone
{
   string   dir;        // "bull" | "bear"
   datetime ts;
   double   top;
   double   bottom;
   int      origin_idx;
};
ObZone g_obs[];

struct LiqZone
{
   string   dir;        // "bull" = liquidity above; "bear" = below
   double   price;
   int      count;
   datetime last_ts;
};
LiqZone g_liq[];

struct Projection
{
   string   dir;
   double   probability;
   double   tp1;
   double   tp2;
   double   structure_target;
   double   big_target;
   double   invalidation;
   datetime way_t[4];
   double   way_p[4];
   bool     valid;
};
Projection g_proj_bull;
Projection g_proj_bear;

//+------------------------------------------------------------------+
//|                          INIT / DEINIT                            |
//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = (StringLen(InpSymbolOverride) > 0) ? InpSymbolOverride : _Symbol;
   g_tf     = (InpTimeframe == PERIOD_CURRENT) ? Period() : InpTimeframe;
   g_prefix = StringFormat("smc_%s_%s_", g_symbol, EnumToString(g_tf));

   ArraySetAsSeries(g_rates, false);  // index 0 = oldest
   ResetDayStats();

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(g_symbol);

   EventSetTimer(MathMax(1, InpUpdateSeconds));
   PrintFormat("SmcVisualEA: %s/%s, prefix=%s, autotrade=%s",
               g_symbol, EnumToString(g_tf), g_prefix,
               InpAutoTrade ? "ON" : "off");

   AnalyseAndDraw();   // initial render
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ClearByPrefix(g_prefix);
   if(InpShowComment) Comment("");
}

void OnTick()
{
   if(InpAutoTrade) ManagePositions();
}

void OnTimer()
{
   AnalyseAndDraw();
   if(InpAutoTrade)
   {
      RolloverDayCheck();
      RolloverKillCheck();
      if(!g_kill_armed) TryTrade();
   }
}

//+------------------------------------------------------------------+
//|                       MAIN ANALYSIS PIPELINE                      |
//+------------------------------------------------------------------+
void AnalyseAndDraw()
{
   if(!LoadBars()) return;
   DetectSwings();
   DetectStructureEvents();
   DetectFVGs();
   DetectOrderBlocks();
   DetectLiquidity();
   BuildProjections();
   ClearByPrefix(g_prefix);
   if(InpDrawFvg)         DrawFvgs();
   if(InpDrawOb)          DrawObs();
   if(InpDrawEvents)      DrawEvents();
   if(InpDrawProjections) DrawProjections();
   if(InpDrawTargets)     DrawTargets();
   if(InpShowComment)     ShowComment();
   g_last_analysis_time = TimeCurrent();
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//|                         BAR LOADING                               |
//+------------------------------------------------------------------+
bool LoadBars()
{
   int got = CopyRates(g_symbol, g_tf, 0, InpBarsWindow, g_rates);
   if(got <= 0)
   {
      PrintFormat("LoadBars: CopyRates failed err=%d", GetLastError());
      g_bars_count = 0;
      return false;
   }
   g_bars_count = got;
   return true;
}

//+------------------------------------------------------------------+
//|                       SWING DETECTION                             |
//+------------------------------------------------------------------+
void DetectSwings()
{
   ArrayResize(g_swing_highs, 0);
   ArrayResize(g_swing_lows, 0);
   int L = InpSwingLookback;
   int n = g_bars_count;
   if(n < 2 * L + 1) return;
   for(int i = L; i < n - L; i++)
   {
      double h = g_rates[i].high;
      double l = g_rates[i].low;
      double max_left  = -DBL_MAX;
      double max_right = -DBL_MAX;
      double min_left  = DBL_MAX;
      double min_right = DBL_MAX;
      for(int k = i - L; k < i; k++)
      {
         if(g_rates[k].high > max_left)  max_left  = g_rates[k].high;
         if(g_rates[k].low  < min_left)  min_left  = g_rates[k].low;
      }
      for(int k = i + 1; k <= i + L; k++)
      {
         if(g_rates[k].high > max_right) max_right = g_rates[k].high;
         if(g_rates[k].low  < min_right) min_right = g_rates[k].low;
      }
      if(h >= max_left && h > max_right)
      {
         SwingPt sp; sp.idx = i; sp.ts = g_rates[i].time; sp.price = h; sp.is_high = true;
         int sz = ArraySize(g_swing_highs); ArrayResize(g_swing_highs, sz + 1);
         g_swing_highs[sz] = sp;
      }
      if(l <= min_left && l < min_right)
      {
         SwingPt sp; sp.idx = i; sp.ts = g_rates[i].time; sp.price = l; sp.is_high = false;
         int sz = ArraySize(g_swing_lows); ArrayResize(g_swing_lows, sz + 1);
         g_swing_lows[sz] = sp;
      }
   }
}

//+------------------------------------------------------------------+
//|                BOS / CHOCH STRUCTURE EVENTS                       |
//+------------------------------------------------------------------+
void DetectStructureEvents()
{
   ArrayResize(g_events, 0);
   g_trend = "";
   int n = g_bars_count;
   if(n == 0) return;
   string last_dir = "";

   // Mutable copies — we remove a swing once it's "consumed" by a break
   SwingPt highs[]; SwingPt lows[];
   ArrayCopy(highs, g_swing_highs);
   ArrayCopy(lows,  g_swing_lows);

   for(int i = 0; i < n; i++)
   {
      double close = g_rates[i].close;

      // Most recent swing high strictly before i
      int rh_idx = -1;
      for(int j = ArraySize(highs) - 1; j >= 0; j--)
         if(highs[j].idx < i) { rh_idx = j; break; }
      // Most recent swing low strictly before i
      int rl_idx = -1;
      for(int j = ArraySize(lows) - 1; j >= 0; j--)
         if(lows[j].idx < i) { rl_idx = j; break; }

      // Bull break
      if(rh_idx >= 0 && close > highs[rh_idx].price)
      {
         StructEv ev;
         ev.kind = (last_dir == "bear") ? "CHOCH" : "BOS";
         ev.dir  = "bull";
         ev.ts   = g_rates[i].time;
         ev.broken_price = highs[rh_idx].price;
         ev.broken_ts    = highs[rh_idx].ts;
         ev.break_idx    = i;
         AppendEvent(ev);
         last_dir = "bull";
         RemoveSwingAt(highs, rh_idx);
         continue;
      }
      // Bear break
      if(rl_idx >= 0 && close < lows[rl_idx].price)
      {
         StructEv ev;
         ev.kind = (last_dir == "bull") ? "CHOCH" : "BOS";
         ev.dir  = "bear";
         ev.ts   = g_rates[i].time;
         ev.broken_price = lows[rl_idx].price;
         ev.broken_ts    = lows[rl_idx].ts;
         ev.break_idx    = i;
         AppendEvent(ev);
         last_dir = "bear";
         RemoveSwingAt(lows, rl_idx);
      }
   }
   if(ArraySize(g_events) > 0)
      g_trend = g_events[ArraySize(g_events) - 1].dir;
}

void AppendEvent(const StructEv &ev)
{
   int sz = ArraySize(g_events);
   ArrayResize(g_events, sz + 1);
   g_events[sz] = ev;
}

void RemoveSwingAt(SwingPt &arr[], int at)
{
   int sz = ArraySize(arr);
   for(int k = at; k < sz - 1; k++) arr[k] = arr[k + 1];
   ArrayResize(arr, sz - 1);
}

//+------------------------------------------------------------------+
//|                          FVG DETECTION                            |
//+------------------------------------------------------------------+
void DetectFVGs()
{
   ArrayResize(g_fvgs, 0);
   int n = g_bars_count;
   for(int i = 1; i < n - 1; i++)
   {
      double prev_h = g_rates[i - 1].high;
      double prev_l = g_rates[i - 1].low;
      double next_h = g_rates[i + 1].high;
      double next_l = g_rates[i + 1].low;
      // Bullish FVG: prev.high < next.low
      if(prev_h < next_l)
      {
         FvgZone z; z.dir = "bull"; z.ts = g_rates[i].time;
         z.bottom = prev_h; z.top = next_l; z.filled = false;
         for(int k = i + 2; k < n; k++)
            if(g_rates[k].low <= z.bottom) { z.filled = true; break; }
         if(i >= n - 1 - InpFvgMaxAge) AppendFvg(z);
      }
      else if(prev_l > next_h)
      {
         FvgZone z; z.dir = "bear"; z.ts = g_rates[i].time;
         z.bottom = next_h; z.top = prev_l; z.filled = false;
         for(int k = i + 2; k < n; k++)
            if(g_rates[k].high >= z.top) { z.filled = true; break; }
         if(i >= n - 1 - InpFvgMaxAge) AppendFvg(z);
      }
   }
}

void AppendFvg(const FvgZone &z)
{
   int sz = ArraySize(g_fvgs);
   ArrayResize(g_fvgs, sz + 1);
   g_fvgs[sz] = z;
}

//+------------------------------------------------------------------+
//|                       ORDER BLOCK DETECTION                       |
//+------------------------------------------------------------------+
void DetectOrderBlocks()
{
   ArrayResize(g_obs, 0);
   for(int e = 0; e < ArraySize(g_events); e++)
   {
      StructEv ev = g_events[e];
      int idx = ev.break_idx;
      int start = MathMax(0, idx - InpObLookback);
      if(ev.dir == "bull")
      {
         for(int i = idx - 1; i >= start; i--)
         {
            if(g_rates[i].close < g_rates[i].open) // bearish candle
            {
               ObZone z; z.dir = "bull"; z.ts = g_rates[i].time;
               z.top = g_rates[i].high; z.bottom = g_rates[i].low; z.origin_idx = i;
               int sz = ArraySize(g_obs); ArrayResize(g_obs, sz + 1);
               g_obs[sz] = z;
               break;
            }
         }
      }
      else
      {
         for(int i = idx - 1; i >= start; i--)
         {
            if(g_rates[i].close > g_rates[i].open) // bullish candle
            {
               ObZone z; z.dir = "bear"; z.ts = g_rates[i].time;
               z.top = g_rates[i].high; z.bottom = g_rates[i].low; z.origin_idx = i;
               int sz = ArraySize(g_obs); ArrayResize(g_obs, sz + 1);
               g_obs[sz] = z;
               break;
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//|                       LIQUIDITY ZONES                             |
//+------------------------------------------------------------------+
void DetectLiquidity()
{
   ArrayResize(g_liq, 0);
   double atr = ComputeAtr();
   if(atr <= 0) return;
   double tol = InpLiqTolAtr * atr;

   ClusterSwings(g_swing_highs, "bull", tol);
   ClusterSwings(g_swing_lows,  "bear", tol);
}

void ClusterSwings(const SwingPt &arr[], const string side, const double tol)
{
   int sz = ArraySize(arr);
   bool used[]; ArrayResize(used, sz); ArrayInitialize(used, 0);
   for(int i = 0; i < sz; i++)
   {
      if(used[i]) continue;
      int    cnt   = 1;
      double sum_p = arr[i].price;
      datetime last_ts = arr[i].ts;
      for(int j = i + 1; j < sz; j++)
      {
         if(MathAbs(arr[j].price - arr[i].price) <= tol)
         {
            cnt++; sum_p += arr[j].price; if(arr[j].ts > last_ts) last_ts = arr[j].ts;
            used[j] = true;
         }
      }
      if(cnt >= 2)
      {
         LiqZone z; z.dir = side; z.price = sum_p / cnt;
         z.count = cnt; z.last_ts = last_ts;
         int n = ArraySize(g_liq); ArrayResize(g_liq, n + 1);
         g_liq[n] = z;
      }
   }
}

double ComputeAtr()
{
   int n = g_bars_count;
   if(n < 2) return 0.0;
   int take = MathMin(InpAtrPeriod, n - 1);
   double sum = 0;
   for(int i = n - take; i < n; i++)
   {
      double tr = MathMax(g_rates[i].high - g_rates[i].low,
                  MathMax(MathAbs(g_rates[i].high - g_rates[i - 1].close),
                          MathAbs(g_rates[i].low  - g_rates[i - 1].close)));
      sum += tr;
   }
   return (take > 0) ? sum / take : 0.0;
}

//+------------------------------------------------------------------+
//|                       PROJECTIONS                                 |
//+------------------------------------------------------------------+
void BuildProjections()
{
   g_proj_bull.valid = false;
   g_proj_bear.valid = false;
   if(g_bars_count == 0) return;
   double price = g_rates[g_bars_count - 1].close;
   datetime now = g_rates[g_bars_count - 1].time;
   double atr = ComputeAtr();
   if(atr <= 0) return;
   long step_s = (long)PeriodSeconds(g_tf);
   if(step_s <= 0) step_s = 60;

   BuildSideProjection(g_proj_bull, "bull", price, atr, now, step_s);
   BuildSideProjection(g_proj_bear, "bear", price, atr, now, step_s);
}

void BuildSideProjection(Projection &out, const string side, const double price,
                         const double atr, const datetime now, const long step_s)
{
   // Sorted unique highs above / lows below price
   double highs[]; double lows[];
   for(int i = 0; i < ArraySize(g_swing_highs); i++)
   {
      double p = g_swing_highs[i].price;
      if(p <= price) continue;
      AppendSorted(highs, p);
   }
   for(int i = 0; i < ArraySize(g_swing_lows); i++)
   {
      double p = g_swing_lows[i].price;
      if(p >= price) continue;
      AppendSorted(lows, p);
   }

   double tp1, tp2, struc, big, inval;
   if(side == "bull")
   {
      tp1 = (ArraySize(highs) > 0) ? highs[0] : (price + 2.0 * atr);
      tp2 = (ArraySize(highs) > 1) ? highs[1] : (tp1 + 1.5 * atr);
      struc = (ArraySize(highs) > 0) ? highs[ArraySize(highs) - 1] : (tp2 + 2.0 * atr);
      big = MathMax(struc, price + 6.0 * atr);
      inval = LastBullInvalidation(price, atr, lows);
   }
   else
   {
      tp1 = (ArraySize(lows) > 0) ? lows[ArraySize(lows) - 1] : (price - 2.0 * atr);
      tp2 = (ArraySize(lows) > 1) ? lows[ArraySize(lows) - 2] : (tp1 - 1.5 * atr);
      struc = (ArraySize(lows) > 0) ? lows[0] : (tp2 - 2.0 * atr);
      big = MathMin(struc, price - 6.0 * atr);
      inval = LastBearInvalidation(price, atr, highs);
   }

   double retrace;
   if(side == "bull") retrace = MathMax(price - 0.5 * atr, inval + 0.1 * atr);
   else               retrace = MathMin(price + 0.5 * atr, inval - 0.1 * atr);

   out.way_t[0] = now;                                 out.way_p[0] = price;
   out.way_t[1] = now + (datetime)(2 * step_s);        out.way_p[1] = retrace;
   out.way_t[2] = now + (datetime)((InpProjLookaheadBars / 2) * step_s); out.way_p[2] = tp1;
   out.way_t[3] = now + (datetime)(InpProjLookaheadBars * step_s);       out.way_p[3] = tp2;

   double base = 0.5;
   if(g_trend == side) base += 0.18;
   else if(g_trend != "") base -= 0.10;
   if(ArraySize(g_events) > 0)
   {
      StructEv last = g_events[ArraySize(g_events) - 1];
      if(last.dir == side)
      {
         if(last.kind == "BOS")   base += 0.08;
         if(last.kind == "CHOCH") base += 0.05;
      }
   }
   int conflu = 0;
   for(int i = 0; i < ArraySize(g_fvgs); i++)
      if(g_fvgs[i].dir == side && !g_fvgs[i].filled) conflu++;
   for(int i = 0; i < ArraySize(g_obs); i++)
   {
      if(side == "bull" && g_obs[i].dir == "bull" && g_obs[i].bottom < price) conflu++;
      if(side == "bear" && g_obs[i].dir == "bear" && g_obs[i].top    > price) conflu++;
   }
   if(conflu > 0) base += MathMin(0.15, 0.04 * conflu);
   if(base < 0.05) base = 0.05;
   if(base > 0.95) base = 0.95;

   out.dir              = side;
   out.probability      = base;
   out.tp1              = tp1;
   out.tp2              = tp2;
   out.structure_target = struc;
   out.big_target       = big;
   out.invalidation     = inval;
   out.valid            = true;
}

void AppendSorted(double &arr[], const double v)
{
   int sz = ArraySize(arr);
   for(int i = 0; i < sz; i++)
      if(MathAbs(arr[i] - v) < 1e-9) return;  // dedup
   ArrayResize(arr, sz + 1);
   arr[sz] = v;
   // insertion sort ascending
   for(int i = sz; i > 0; i--)
   {
      if(arr[i] < arr[i - 1])
      {
         double t = arr[i]; arr[i] = arr[i - 1]; arr[i - 1] = t;
      }
      else break;
   }
}

double LastBullInvalidation(const double price, const double atr, const double &lows[])
{
   double inval = price - 3.0 * atr;
   // Recent bull OBs (last 3) — invalidation = min(bottoms)
   double obi = DBL_MAX;
   int seen = 0;
   for(int i = ArraySize(g_obs) - 1; i >= 0 && seen < 3; i--)
   {
      if(g_obs[i].dir == "bull")
      {
         if(g_obs[i].bottom < obi) obi = g_obs[i].bottom;
         seen++;
      }
   }
   if(obi != DBL_MAX) return obi;
   if(ArraySize(lows) > 0) return lows[ArraySize(lows) - 1];
   return inval;
}

double LastBearInvalidation(const double price, const double atr, const double &highs[])
{
   double inval = price + 3.0 * atr;
   double obi = -DBL_MAX;
   int seen = 0;
   for(int i = ArraySize(g_obs) - 1; i >= 0 && seen < 3; i--)
   {
      if(g_obs[i].dir == "bear")
      {
         if(g_obs[i].top > obi) obi = g_obs[i].top;
         seen++;
      }
   }
   if(obi != -DBL_MAX) return obi;
   if(ArraySize(highs) > 0) return highs[0];
   return inval;
}

//+------------------------------------------------------------------+
//|                       DRAWING PRIMITIVES                          |
//+------------------------------------------------------------------+
void RecreateRect(const string name, const datetime t1, const double p1,
                  const datetime t2, const double p2,
                  const color clr, const bool fill)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2)) return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FILL, fill);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
}

void RecreateTrend(const string name, const datetime t1, const double p1,
                   const datetime t2, const double p2,
                   const color clr, const int style, const int width)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2)) return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

void RecreateLabel(const string name, const datetime t, const double p,
                   const string text, const color clr, const int size = 9)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, p)) return;
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

void ClearByPrefix(const string prefix)
{
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string n = ObjectName(0, i);
      if(StringFind(n, prefix) == 0) ObjectDelete(0, n);
   }
}

//+------------------------------------------------------------------+
//|                          DRAW HELPERS                             |
//+------------------------------------------------------------------+
datetime LastBarTime()
{
   return (g_bars_count > 0) ? g_rates[g_bars_count - 1].time : (datetime)TimeCurrent();
}

long BarStepSeconds()
{
   long s = (long)PeriodSeconds(g_tf);
   return (s > 0) ? s : 60;
}

void DrawFvgs()
{
   int total = ArraySize(g_fvgs);
   int drawn = 0;
   datetime tend = LastBarTime() + (datetime)(5 * BarStepSeconds());
   // Take the most recent unfilled (latest first)
   for(int i = total - 1; i >= 0 && drawn < InpMaxZonesDrawn; i--)
   {
      FvgZone z = g_fvgs[i];
      if(z.filled) continue;
      color clr = (z.dir == "bull") ? InpColorFvgBull : InpColorFvgBear;
      string name = StringFormat("%sfvg_%d", g_prefix, i);
      RecreateRect(name, z.ts, z.top, tend, z.bottom, clr, true);
      drawn++;
   }
}

void DrawObs()
{
   int total = ArraySize(g_obs);
   int drawn = 0;
   datetime tend = LastBarTime() + (datetime)(5 * BarStepSeconds());
   for(int i = total - 1; i >= 0 && drawn < InpMaxZonesDrawn; i--)
   {
      ObZone z = g_obs[i];
      color clr = (z.dir == "bull") ? InpColorObBull : InpColorObBear;
      string name = StringFormat("%sob_%d", g_prefix, i);
      RecreateRect(name, z.ts, z.top, tend, z.bottom, clr, true);
      drawn++;
   }
}

void DrawEvents()
{
   int total = ArraySize(g_events);
   int from = MathMax(0, total - 5);
   for(int i = from; i < total; i++)
   {
      StructEv ev = g_events[i];
      datetime t1 = ev.broken_ts;
      datetime t2 = (ev.break_idx < g_bars_count) ? g_rates[ev.break_idx].time : LastBarTime();
      color clr = (ev.dir == "bull") ? InpColorBosBull : InpColorBosBear;
      string ln = StringFormat("%sev_%d", g_prefix, i);
      string lb = StringFormat("%sev_%d_lbl", g_prefix, i);
      RecreateTrend(ln, t1, ev.broken_price, t2, ev.broken_price, clr, STYLE_DOT, 1);
      RecreateLabel(lb, t2, ev.broken_price,
                    StringFormat("%s %s", ev.kind, (ev.dir == "bull") ? "UP" : "DOWN"),
                    clr, 8);
   }
}

void DrawProjections()
{
   if(g_proj_bull.valid) DrawSideProjection(g_proj_bull, InpColorPathBull, "bull");
   if(g_proj_bear.valid) DrawSideProjection(g_proj_bear, InpColorPathBear, "bear");
}

void DrawSideProjection(const Projection &p, const color clr, const string sub)
{
   for(int i = 0; i < 3; i++)
   {
      string name = StringFormat("%sproj_%s_%d", g_prefix, sub, i);
      RecreateTrend(name, p.way_t[i], p.way_p[i], p.way_t[i + 1], p.way_p[i + 1],
                    clr, STYLE_DASH, 2);
   }
}

void DrawTargets()
{
   if(g_proj_bull.valid) DrawTargetsForSide(g_proj_bull, "bull");
   if(g_proj_bear.valid) DrawTargetsForSide(g_proj_bear, "bear");
}

void DrawTargetsForSide(const Projection &p, const string side)
{
   datetime t_left = (g_bars_count > 30) ? g_rates[g_bars_count - 30].time
                                          : (g_bars_count > 0 ? g_rates[0].time : LastBarTime());
   datetime t_right = p.way_t[3];
   color tp_clr  = InpColorTpLine;
   color inv_clr = InpColorInvalLine;

   double levels[5] = { p.tp1, p.tp2, p.structure_target, p.big_target, p.invalidation };
   string tags[5]   = { "tp1", "tp2", "struct", "big", "inval" };
   color  clrs[5]   = { tp_clr, tp_clr, tp_clr, tp_clr, inv_clr };

   for(int i = 0; i < 5; i++)
   {
      string ln = StringFormat("%sproj_%s_%s_ln", g_prefix, side, tags[i]);
      string lb = StringFormat("%sproj_%s_%s_lbl", g_prefix, side, tags[i]);
      RecreateTrend(ln, t_left, levels[i], t_right, levels[i], clrs[i], STYLE_DOT, 1);
      string side_up = (side == "bull") ? "UP" : "DOWN";
      RecreateLabel(lb, t_right, levels[i],
                    StringFormat("%s %s %.5f", side_up, tags[i], levels[i]),
                    clrs[i], 8);
   }
}

void ShowComment()
{
   string text = "";
   text += StringFormat("=== SMC Visual EA — %s %s ===\n", g_symbol, EnumToString(g_tf));
   text += StringFormat("Trend: %s | swings H/L: %d / %d | events: %d\n",
                        (g_trend == "" ? "-" : g_trend),
                        ArraySize(g_swing_highs), ArraySize(g_swing_lows),
                        ArraySize(g_events));
   text += StringFormat("FVGs: %d  OBs: %d  Liquidity: %d\n",
                        ArraySize(g_fvgs), ArraySize(g_obs), ArraySize(g_liq));
   if(g_proj_bull.valid && g_proj_bear.valid)
   {
      Projection best = (g_proj_bull.probability >= g_proj_bear.probability)
                        ? g_proj_bull : g_proj_bear;
      string dir = (best.dir == "bull") ? "UP" : "DOWN";
      text += StringFormat(
         "\n%s %s\n"
         "Direction: %s\n"
         "Probability: %.0f%%\n"
         "Near target: TP1 %.5f\n"
         "Next target: TP2 %.5f\n"
         "Structure target: %.5f\n"
         "Big target: %.5f\n"
         "Invalidation: %.5f\n",
         g_symbol, EnumToString(g_tf),
         dir, best.probability * 100,
         best.tp1, best.tp2, best.structure_target,
         best.big_target, best.invalidation);
   }
   text += StringFormat("\nAuto-trade: %s | trades today: %d | kill: %s\n",
                        InpAutoTrade ? "ON" : "off", g_trades_today,
                        g_kill_armed ? "ARMED" : "ok");
   Comment(text);
}

//+------------------------------------------------------------------+
//|                       OPTIONAL AUTO-TRADE                         |
//+------------------------------------------------------------------+
void ResetDayStats()
{
   g_day_start = StringToTime(TimeToString(TimeCurrent(), TIME_DATE));
   g_day_start_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_trades_today = 0;
   g_kill_armed = false;
}

void RolloverDayCheck()
{
   datetime today = StringToTime(TimeToString(TimeCurrent(), TIME_DATE));
   if(today != g_day_start) ResetDayStats();
}

void RolloverKillCheck()
{
   double dd = g_day_start_equity - AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_day_start_equity <= 0) return;
   double dd_pct = 100.0 * dd / g_day_start_equity;
   if(dd_pct >= InpMaxDailyLossPct && !g_kill_armed)
   {
      g_kill_armed = true;
      PrintFormat("KILL ARMED: daily loss %.2f%% breached (cap %.2f%%)",
                  dd_pct, InpMaxDailyLossPct);
   }
}

bool RiskOK()
{
   if(g_kill_armed) return false;
   if(g_trades_today >= InpMaxTradesPerDay) return false;
   if(TimeCurrent() - g_last_trade_time < InpMinSeconds) return false;
   if(PositionsTotalForSymbol() > 0) return false;  // одоо position нээлттэй
   return true;
}

int PositionsTotalForSymbol()
{
   int cnt = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         cnt++;
   }
   return cnt;
}

double LotForRisk(const double sl_distance)
{
   if(sl_distance <= 0) return 0;
   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct / 100.0;
   double tick_value = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(g_symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size <= 0 || tick_value <= 0) return SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   double loss_per_lot = (sl_distance / tick_size) * tick_value;
   if(loss_per_lot <= 0) return SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   double lots = risk_money / loss_per_lot;
   double step = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);
   double minl = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   double maxl = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) lots = MathFloor(lots / step) * step;
   if(lots < minl) lots = minl;
   if(lots > maxl) lots = maxl;
   return NormalizeDouble(lots, 2);
}

void TryTrade()
{
   if(!RiskOK()) return;
   if(!g_proj_bull.valid && !g_proj_bear.valid) return;

   Projection best = g_proj_bull.probability >= g_proj_bear.probability
                     ? g_proj_bull : g_proj_bear;
   if(!best.valid) return;
   if(best.probability < InpProbThreshold) return;

   double price_ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   double price_bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double tp = InpUseStrucutreTarget ? best.structure_target : best.tp1;

   if(best.dir == "bull")
   {
      // Entry: price within nearest unfilled bull OB or at current ask
      if(!IsPriceNearBullOB(price_ask)) return;
      double sl_dist = price_ask - best.invalidation;
      if(sl_dist <= 0) return;
      double lots = LotForRisk(sl_dist);
      if(lots <= 0) return;
      string cmt = StringFormat("smcv_bull_%d", (int)TimeCurrent());
      if(g_trade.Buy(lots, g_symbol, 0, best.invalidation, tp, cmt))
      {
         g_trades_today++;
         g_last_trade_time = TimeCurrent();
         PrintFormat("BUY %s lots=%.2f sl=%.5f tp=%.5f prob=%.0f%%",
                     g_symbol, lots, best.invalidation, tp, best.probability * 100);
      }
      else
         PrintFormat("Buy failed: retcode=%d", g_trade.ResultRetcode());
   }
   else
   {
      if(!IsPriceNearBearOB(price_bid)) return;
      double sl_dist = best.invalidation - price_bid;
      if(sl_dist <= 0) return;
      double lots = LotForRisk(sl_dist);
      if(lots <= 0) return;
      string cmt = StringFormat("smcv_bear_%d", (int)TimeCurrent());
      if(g_trade.Sell(lots, g_symbol, 0, best.invalidation, tp, cmt))
      {
         g_trades_today++;
         g_last_trade_time = TimeCurrent();
         PrintFormat("SELL %s lots=%.2f sl=%.5f tp=%.5f prob=%.0f%%",
                     g_symbol, lots, best.invalidation, tp, best.probability * 100);
      }
      else
         PrintFormat("Sell failed: retcode=%d", g_trade.ResultRetcode());
   }
}

bool IsPriceNearBullOB(const double price)
{
   double atr = ComputeAtr();
   double tol = MathMax(atr * 0.5, SymbolInfoDouble(g_symbol, SYMBOL_POINT) * 50);
   for(int i = ArraySize(g_obs) - 1; i >= 0; i--)
   {
      if(g_obs[i].dir != "bull") continue;
      if(price >= g_obs[i].bottom - tol && price <= g_obs[i].top + tol)
         return true;
   }
   return false;
}

bool IsPriceNearBearOB(const double price)
{
   double atr = ComputeAtr();
   double tol = MathMax(atr * 0.5, SymbolInfoDouble(g_symbol, SYMBOL_POINT) * 50);
   for(int i = ArraySize(g_obs) - 1; i >= 0; i--)
   {
      if(g_obs[i].dir != "bear") continue;
      if(price >= g_obs[i].bottom - tol && price <= g_obs[i].top + tol)
         return true;
   }
   return false;
}

void ManagePositions()
{
   // Trail SL when price moves favourably by ATR
   double atr = ComputeAtr();
   if(atr <= 0) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double price = (type == POSITION_TYPE_BUY)
                     ? SymbolInfoDouble(g_symbol, SYMBOL_BID)
                     : SymbolInfoDouble(g_symbol, SYMBOL_ASK);
      double new_sl = sl;
      if(type == POSITION_TYPE_BUY)
      {
         double profit = price - entry;
         if(profit > 1.5 * atr)
         {
            double cand = price - 1.0 * atr;
            if(cand > sl) new_sl = cand;
         }
      }
      else
      {
         double profit = entry - price;
         if(profit > 1.5 * atr)
         {
            double cand = price + 1.0 * atr;
            if(cand < sl || sl == 0) new_sl = cand;
         }
      }
      if(MathAbs(new_sl - sl) > _Point)
         g_trade.PositionModify(t, new_sl, tp);
   }
}

//+------------------------------------------------------------------+
