//+------------------------------------------------------------------+
//|                                    SMC_Pure_EA_v3_Safe.mq5       |
//|   Pure SMC Expert Advisor v3.2-SAFE                               |
//|   Designed for XAUUSD (GOLD)                                      |
//|                                                                    |
//|   🛡 ULTRA-SAFE EDITION:                                           |
//|     - Өдөрт max 2 арилжаа                                        |
//|     - 0.3% эрсдэл/арилжаа, 1.0% өдрийн max алдагдал             |
//|     - 5/7 confluence шаардлага                                    |
//|     - London+NY overlap only (13-17 GMT)                         |
//|     - Spread, ATR, Monday-morning, PD-alignment филтер            |
//|     - 2 алдагдсаны дараа 24 цаг cooldown                         |
//|                                                                    |
//|   ⚠ ТАЙЛБАР: 100% АЛДАГДАЛГҮЙ АРИЛЖАА БОДИТОЙ БАЙДАГГҮЙ.       |
//|      Энэ хувилбар зөвхөн алдагдлын магадлалыг багасгана.          |
//+------------------------------------------------------------------+
#property copyright "SMC Pure EA v3.4-SLHUNT"
#property link      ""
#property version   "3.40"
#property strict
#property description "SMC v3.4: SL HUNT reversal + OB retest dual entry | 2 trade/day"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//=== ENUMS ===========================================================
enum ENUM_TP_MODE   { TP_PARTIAL=0, TP_SINGLE_TRAIL=1 };
enum ENUM_EA_MODE   { MODE_AUTO=0, MODE_MANUAL=1 };
enum ENUM_SMC_SETUP { SMC_NONE=0, SMC_CHOCH_OB=1, SMC_BOS_OB=2 };

//=== INPUT PARAMETERS ================================================
input group           "══════ Ерөнхий (ULTRA-SAFE) ══════"
input double          InpRiskPct        = 0.3;           // Эрсдэл (% дансны) [SAFE: 0.3]
input int             InpMagic          = 777032;        // Magic Number
input int             InpSlippage       = 20;            // Slippage (points)
input double          InpSLBuffer       = 8.0;           // SL буфер (pip) [SAFE: илүү зай]

input group           "══════ 3-Tier TF ══════"
input ENUM_TIMEFRAMES InpHTF            = PERIOD_M15;    // Чиглэл TF (Bias)
input ENUM_TIMEFRAMES InpMTF            = PERIOD_M5;     // Баталгаажуулалт TF
input ENUM_TIMEFRAMES InpLTF            = PERIOD_M1;     // Entry TF

input group           "══════ SMC Engine ══════"
input int             InpHTF_Pivot      = 8;             // HTF swing pivot
input int             InpMTF_Pivot      = 4;             // MTF swing pivot
input int             InpHTF_Lookback   = 300;           // HTF lookback
input int             InpMTF_Lookback   = 200;           // MTF lookback
input int             InpLTF_Lookback   = 100;           // LTF lookback
input int             InpMinConfluence  = 3;             // Min confluence [FLEX: 3/8]
input double          InpPDPct          = 0.30;          // PD zone size
input bool            InpRequirePDAlign = false;         // PD zone [FLEX: off]
input double          InpPDExtremeBlock = 0.05;          // Extreme блок % (5%)

input group           "══════ TP тохиргоо (SAFE) ══════"
input ENUM_TP_MODE    InpTPMode         = TP_PARTIAL;    // TP горим
input double          InpTP1_RR         = 1.0;           // TP1 RR [SAFE: 1.0 түргэн]
input double          InpTP2_RR         = 2.0;           // TP2 RR
input double          InpTP3_RR         = 3.0;           // TP3 RR
input int             InpTP1_Pct        = 70;            // TP1 хаах % [SAFE: 70%]
input int             InpTP2_Pct        = 20;            // TP2 хаах %
input double          InpSingleTP_RR    = 1.5;           // Single TP RR
input double          InpTrailStart_RR  = 0.8;           // Trail эхлэх RR
input double          InpTrailStep      = 4.0;           // Trail step (pip)

input group           "══════ Аюулгүй байдал (HARDENED) ══════"
input int             InpMaxTradesDay   = 2;             // Өдрийн max арилжаа [SAFE: 2]
input double          InpMaxDailyLoss   = 1.0;           // Өдрийн max алдагдал % [SAFE: 1.0]
input double          InpMaxLotSize     = 0.03;          // Max lot size [SAFE: 0.03]
input bool            InpSessionFilter  = true;          // Session шүүлтүүр
input int             InpSessionStart   = 8;             // Session эхлэх GMT [BALANCED: London+NY]
input int             InpSessionEnd     = 20;            // Session дуусах GMT
input int             InpMaxSpreadPts   = 50;            // Max spread (points) [FLEX]
input double          InpMinSLPoints    = 40.0;          // Min SL зай (points) [FLEX]
input bool            InpUseATRFilter   = false;         // ATR volatility filter [FLEX: off]
input int             InpATRPeriod      = 14;            // ATR period (M5)
input double          InpATRMinMult     = 0.3;           // Min ATR [FLEX]
input double          InpATRMaxMult     = 4.0;           // Max ATR [FLEX]

input group           "══════ Алдагдлын хамгаалалт (STRICT) ══════"
input int             InpMaxConsecLoss  = 2;             // Consec loss хязгаар [SAFE: 2]
input int             InpCooldownHours  = 24;            // Cooldown (цаг) [SAFE: 24]
input bool            InpNoFriday       = true;          // Баасан NO TRADE
input bool            InpNoMondayAM     = true;          // Даваа 0-10 GMT NO TRADE (gap risk)
input bool            InpReduceAfterLoss = true;         // Lot бууруулах

input group           "══════ Мэдээний шүүлтүүр ══════"
input bool            InpNewsFilter     = true;          // Мэдээний цагийг алгасах
input int             InpNewsBeforeMin  = 60;            // Өмнө (минут) [SAFE: 60]
input int             InpNewsAfterMin   = 60;            // Дараа (минут) [SAFE: 60]
input bool            InpBlockNFP       = true;          // NFP
input bool            InpBlockFOMC      = true;          // FOMC
input bool            InpBlockCPI       = true;          // CPI
input int             InpCustomNewsHour1 = -1;           // Custom 1 (GMT, -1=off)
input int             InpCustomNewsMin1  = 0;
input int             InpCustomNewsHour2 = -1;           // Custom 2
input int             InpCustomNewsMin2  = 0;

input group           "══════ v3.3 COUNTER-TREND ХАМГААЛАЛТ ══════"
input bool            InpUseH1Trend      = false;        // H1 trend (FLEX: off, SL hunt counter-trend safe)
input int             InpH1MAPeriod      = 50;           // H1 MA period
input bool            InpUseH4Trend      = false;        // H4 trend (FLEX: off)
input int             InpH4MAPeriod      = 50;           // H4 MA period
input bool            InpRequireRejection = false;       // M5 rejection (FLEX: off, OB path only)
input double          InpMinWickRatio    = 1.2;          // Wick/body ratio
input int             InpMinOBAgeBars    = 2;            // OB min age (BALANCED)
input int             InpMaxOBAgeBars    = 60;           // OB max age (BALANCED)
input bool            InpRequireSweep    = false;        // Sweep (BALANCED: off)
input int             InpSweepLookback   = 20;           // Sweep lookback
input double          InpSweepMinPips    = 3.0;          // Min sweep distance
input int             InpM1ConfirmBars   = 1;            // M1 confirm bars (BALANCED)
input bool            InpUseStructuralSL = true;         // Structural SL (чухал)
input int             InpStructLookback  = 15;           // Struct lookback
input double          InpMaxChasePips    = 25.0;         // Max chase (BALANCED)
input bool            InpDebugBlocks     = true;         // Debug: яагаад block хийв?

input group           "══════ v3.4 SL HUNT ENTRY ══════"
input bool            InpUseSLHunt       = true;         // SL hunt reversal entry ON
input bool            InpUseOBRetest     = true;         // OB retest entry ON
input int             InpSLHuntLookback  = 25;           // Swing low/high хайх (M5 лаа)
input int             InpSLHuntScanBars  = 4;            // Хамгийн сүүлийн N лаанд хайх
input double          InpSLHuntMinPips   = 2.0;          // Min wick distance (pip)
input double          InpSLHuntMaxPips   = 50.0;         // Max wick distance (хэт хол биш)
input double          InpSLHuntCloseBack = 0.5;          // Close back хувь (wick-ийн 50%)
input double          InpSLHuntSLBufPips = 5.0;          // SL буфер sweep low/high-ээс

input group           "══════ Chart Drawing ══════"
input bool            InpDrawOB         = true;
input bool            InpDrawSwings     = true;
input bool            InpDrawBreaks     = true;
input bool            InpDrawPD         = true;
input bool            InpDrawEntry      = true;
input bool            InpDrawHistory    = true;

input group           "══════ Өнгө ══════"
input color           InpBullClr        = C'0,230,118';
input color           InpBearClr        = C'255,82,82';
input color           InpChochClr       = C'255,152,0';
input color           InpBosClr         = C'156,204,101';
input color           InpPremClr        = C'239,83,80';
input color           InpDiscClr        = C'102,187,106';
input color           InpEqClr          = C'144,164,174';
input color           InpEntryClr       = C'255,235,59';
input color           InpSLClr          = C'255,23,68';
input color           InpTPClr          = C'0,230,118';

input group           "══════ Горим & Панел ══════"
input ENUM_EA_MODE    InpDefaultMode    = MODE_AUTO;
input int             InpPanelX         = 10;
input int             InpPanelY         = 50;
input color           InpPanelBG        = C'25,25,38';
input color           InpPanelText      = C'200,200,210';
input color           InpBtnActive      = C'0,150,255';
input color           InpBtnInactive    = C'60,60,75';

//=== CONSTANTS =======================================================
#define EA_PREFIX     "SMCv3S_"
#define PNL_PREFIX    "SMCv3S_PNL_"
#define DRW_PREFIX    "SMCv3S_DRW_"
#define MAX_PIVOTS    50
#define MAX_OB        12

//=== STRUCTURES ======================================================
struct SPivot
{
   int      barIdx;
   double   price;
   bool     isHigh;
   int      label;
   datetime time;
};

struct SOBZone
{
   double   top, bottom;
   datetime timeStart;
   bool     isBullish, isValid;
   int      barIdx;
};

struct SBreakEvent
{
   double   price;
   datetime time;
   bool     isBullish;
   bool     isBOS;
   int      barIdx;
};

struct SSetup
{
   bool          valid;
   bool          isBuy;
   ENUM_SMC_SETUP type;
   double        entry, sl, tp1, tp2, tp3;
   double        obTop, obBot;
   int           confluence;
   string        reason;
   datetime      signalTime;
};

struct STier
{
   int         bias;
   string      biasText;
   double      pdHigh, pdLow, premBot, discTop, eqLine;
   SPivot      htfPivots[];
   int         nHTF;
   SPivot      mtfPivots[];
   int         nMTF;
   SOBZone     mtfOBs[];
   int         nOB;
   SBreakEvent mtfBrks[];
   int         nBrk;
   SSetup      setup;
   bool        m5Ready;
   SOBZone     activeOB;
};

struct SSLHunt
{
   bool     valid;
   bool     isBuy;
   double   sweepLevel;     // Swept swing low/high
   double   sweepExtreme;   // Deepest point of wick (for SL)
   double   reclaimPrice;   // Close price after sweep
   datetime sweepTime;
   int      sweepBarIdx;
};

//=== GLOBALS =========================================================
CTrade         g_trade;
CPositionInfo  g_pos;
COrderInfo     g_order;

int            g_mode;
STier          g_tier;
int            g_todayTrades;
double         g_accountStart;
bool           g_panelOK;
int            g_seq;
bool           g_waitingForClose;
int            g_consecLoss;
datetime       g_cooldownUntil;
double         g_lossMultiplier;

// ATR cache
double         g_atrAvg;
datetime       g_atrLastCalc;

// SL Hunt active flag
bool           g_isSLHuntSetup;
SSLHunt        g_slHunt;

//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippage);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   g_mode = InpDefaultMode;
   g_todayTrades = 0;
   g_accountStart = AccountInfoDouble(ACCOUNT_BALANCE);
   g_panelOK = false;
   g_seq = 0;
   g_waitingForClose = false;
   g_consecLoss = 0;
   g_cooldownUntil = 0;
   g_lossMultiplier = 1.0;
   g_atrAvg = 0;
   g_atrLastCalc = 0;
   g_isSLHuntSetup = false;

   g_tier.bias = 0; g_tier.biasText = "---";
   g_tier.setup.valid = false; g_tier.m5Ready = false;
   g_tier.nHTF = 0; g_tier.nMTF = 0; g_tier.nOB = 0; g_tier.nBrk = 0;

   CheckTradeHistory();
   CreatePanel();

   Print("🛡 SMC v3.2-SAFE эхэллээ | Risk=", InpRiskPct, "% | MaxDay=", InpMaxTradesDay,
         " | Conf=", InpMinConfluence, " | Session=", InpSessionStart, "-", InpSessionEnd, " GMT");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, EA_PREFIX);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//|  MAIN TICK                                                         |
//+------------------------------------------------------------------+
void OnTick()
{
   int openPos = CountMyPositions();
   int openOrd = CountMyOrders();
   g_waitingForClose = (openPos > 0 || openOrd > 0);

   if(openPos > 0)
      ManageOpenPositions();

   static datetime lastHTF = 0, lastMTF = 0, lastLTF = 0;
   bool newHTF = false, newMTF = false, newLTF = false;

   datetime tHTF = iTime(_Symbol, InpHTF, 0);
   datetime tMTF = iTime(_Symbol, InpMTF, 0);
   datetime tLTF = iTime(_Symbol, InpLTF, 0);

   if(tHTF != lastHTF) { lastHTF = tHTF; newHTF = true; }
   if(tMTF != lastMTF) { lastMTF = tMTF; newMTF = true; }
   if(tLTF != lastLTF) { lastLTF = tLTF; newLTF = true; }

   if(!newHTF && !newMTF && !newLTF) return;

   ResetDaily();
   if(!SafetyOK()) { UpdatePanel(); return; }

   if(newHTF) AnalyzeBias();
   if(newMTF && g_tier.bias != 0) AnalyzeMTF();

   if(newLTF && !g_waitingForClose && g_tier.m5Ready && g_mode == MODE_AUTO)
   {
      CheckM1Entry();
      if(g_tier.setup.valid)
      {
         ExecuteEntry(g_tier.setup);
         g_waitingForClose = true;
      }
   }

   DrawAll();
   UpdatePanel();
}

//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam,
                  const double &dparam, const string &sparam)
{
   if(id != CHARTEVENT_OBJECT_CLICK) return;

   if(sparam == PNL_PREFIX + "BTN_MODE")
   {
      g_mode = (g_mode == MODE_AUTO) ? MODE_MANUAL : MODE_AUTO;
      ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      UpdatePanel(); return;
   }
   if(sparam == PNL_PREFIX + "BTN_BUY")
   {
      ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      if(!g_waitingForClose) ManualEntry(true);
      else Print("⚠ Өмнөх арилжаа хаагдаагүй байна");
      return;
   }
   if(sparam == PNL_PREFIX + "BTN_SELL")
   {
      ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      if(!g_waitingForClose) ManualEntry(false);
      else Print("⚠ Өмнөх арилжаа хаагдаагүй байна");
      return;
   }
   if(sparam == PNL_PREFIX + "BTN_CLOSE")
   {
      ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      CloseAll(); return;
   }
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong dealTicket = trans.deal;
   if(dealTicket == 0) return;
   if(!HistoryDealSelect(dealTicket)) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_MAGIC) != InpMagic) return;
   if(HistoryDealGetString(dealTicket, DEAL_SYMBOL) != _Symbol) return;
   if(HistoryDealGetInteger(dealTicket, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT)
                 + HistoryDealGetDouble(dealTicket, DEAL_SWAP)
                 + HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);

   if(profit < 0)
   {
      g_consecLoss++;
      Print("📉 Алдагдал #", g_consecLoss, ": $", DoubleToString(profit, 2));

      if(InpReduceAfterLoss)
      {
         if(g_consecLoss >= 3)      g_lossMultiplier = 0.25;
         else if(g_consecLoss >= 2) g_lossMultiplier = 0.50;
         else if(g_consecLoss >= 1) g_lossMultiplier = 0.75;
      }

      if(g_consecLoss >= InpMaxConsecLoss)
      {
         g_cooldownUntil = TimeCurrent() + InpCooldownHours * 3600;
         Print("🛑 ", g_consecLoss, " consec loss! Cooldown until: ",
               TimeToString(g_cooldownUntil));
         Alert("SMC SAFE: ", g_consecLoss, " дараалсан алдагдал! ",
               InpCooldownHours, " цаг cooldown.");
      }
   }
   else
   {
      if(g_consecLoss > 0)
         Print("✅ Ашигтай! Streak тэглэгдлээ (өмнө: ", g_consecLoss, ")");
      g_consecLoss = 0;
      g_lossMultiplier = 1.0;
      g_cooldownUntil = 0;
   }
}

//+------------------------------------------------------------------+
//|  TIER 1: M15 BIAS                                                  |
//+------------------------------------------------------------------+
void AnalyzeBias()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, InpHTF, 0, InpHTF_Lookback, r);
   if(n < 50) { g_tier.bias = 0; g_tier.biasText = "NO DATA"; return; }

   int nP = CollectPivots(r, n, InpHTF_Pivot, g_tier.htfPivots);
   g_tier.nHTF = nP;
   if(nP < 4) { g_tier.bias = 0; g_tier.biasText = "NEUTRAL"; return; }
   ClassifyPivots(g_tier.htfPivots, nP);

   int bS = 0, eS = 0;
   for(int i = 0; i < MathMin(nP, 4); i++)
   {
      if(g_tier.htfPivots[i].label == 0 || g_tier.htfPivots[i].label == 1) bS++;
      if(g_tier.htfPivots[i].label == 2 || g_tier.htfPivots[i].label == 3) eS++;
   }

   int lastDir = 0;
   for(int i = 0; i < MathMin(nP, 8); i++)
   {
      if(g_tier.htfPivots[i].label == 0) { lastDir = 1; break; }
      if(g_tier.htfPivots[i].label == 3) { lastDir = 2; break; }
   }

   double maSum = 0;
   int maPer = MathMin(200, n);
   for(int i = 0; i < maPer; i++) maSum += r[i].close;
   double ma = maSum / maPer;
   int maDir = (r[0].close > ma) ? 1 : 2;

   int tBull = 0, tBear = 0;
   if(bS > eS) tBull++; else if(eS > bS) tBear++;
   if(lastDir == 1) tBull += 2; else if(lastDir == 2) tBear += 2;
   if(maDir == 1) tBull++; else tBear++;

   if(tBull > tBear)      { g_tier.bias = 1; g_tier.biasText = "BULLISH ▲"; }
   else if(tBear > tBull) { g_tier.bias = 2; g_tier.biasText = "BEARISH ▼"; }
   else                   { g_tier.bias = 0; g_tier.biasText = "NEUTRAL ◆"; }

   double hi = -DBL_MAX, lo = DBL_MAX;
   for(int i = 0; i < MathMin(nP, 6); i++)
   {
      if(g_tier.htfPivots[i].price > hi) hi = g_tier.htfPivots[i].price;
      if(g_tier.htfPivots[i].price < lo) lo = g_tier.htfPivots[i].price;
   }
   g_tier.pdHigh = hi; g_tier.pdLow = lo;
   double rng = hi - lo;
   if(rng > 0)
   {
      g_tier.premBot = hi - rng * InpPDPct;
      g_tier.discTop = lo + rng * InpPDPct;
      g_tier.eqLine  = lo + rng * 0.5;
   }

   Print("🔍 M15 Bias: swing=", bS, "/", eS,
         " last=", lastDir, " MA=", maDir, " → ", g_tier.biasText);
}

//+------------------------------------------------------------------+
//|  TIER 2: M5 CONFIRMATION                                           |
//+------------------------------------------------------------------+
void AnalyzeMTF()
{
   g_tier.m5Ready = false;
   g_tier.setup.valid = false;
   g_isSLHuntSetup = false;

   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, InpMTF, 0, InpMTF_Lookback, r);
   if(n < 30) return;

   g_tier.nMTF = CollectPivots(r, n, InpMTF_Pivot, g_tier.mtfPivots);
   if(g_tier.nMTF >= 2) ClassifyPivots(g_tier.mtfPivots, g_tier.nMTF);

   CollectOBs(r, n);
   CollectBreaks(r, n);

   bool wBuy = (g_tier.bias == 1);

   // ★ v3.4: SL HUNT entry — OB retest хэрэггүй, sweep болсны дараа entry
   if(InpUseSLHunt)
   {
      SSLHunt hunt;
      if(DetectSLHunt(wBuy, hunt))
      {
         g_slHunt = hunt;
         g_tier.m5Ready = true;
         g_isSLHuntSetup = true;

         // Synthetic OB — sweep zone болгон ашиглана
         g_tier.activeOB.top = wBuy ? hunt.sweepLevel : hunt.sweepExtreme;
         g_tier.activeOB.bottom = wBuy ? hunt.sweepExtreme : hunt.sweepLevel;
         g_tier.activeOB.timeStart = hunt.sweepTime;
         g_tier.activeOB.isBullish = wBuy;
         g_tier.activeOB.isValid = true;
         g_tier.activeOB.barIdx = hunt.sweepBarIdx;

         g_tier.setup.valid = false;
         g_tier.setup.isBuy = wBuy;
         g_tier.setup.type = SMC_CHOCH_OB;
         g_tier.setup.obTop = g_tier.activeOB.top;
         g_tier.setup.obBot = g_tier.activeOB.bottom;
         g_tier.setup.reason = wBuy ? "SL-HUNT-BUY" : "SL-HUNT-SELL";

         Print("🎯 SL HUNT: ", (wBuy ? "BULL" : "BEAR"),
               " sweep=", DoubleToString(hunt.sweepLevel, _Digits),
               " extreme=", DoubleToString(hunt.sweepExtreme, _Digits),
               " reclaim=", DoubleToString(hunt.reclaimPrice, _Digits));
         return;
      }
   }

   // OB retest path (хуучин логик)
   if(!InpUseOBRetest) return;
   if(g_tier.nBrk == 0 || g_tier.nOB == 0) return;

   // ★ v3.3: H1 trend alignment заавал
   if(InpUseH1Trend && !IsHTFTrendAligned(wBuy, PERIOD_H1, InpH1MAPeriod))
   {
      static datetime lastH1 = 0;
      if(TimeCurrent() - lastH1 > 300)
      { Print("🚫 H1 trend эсрэг — counter-trend entry цуцлав"); lastH1 = TimeCurrent(); }
      return;
   }

   // ★ v3.3: H4 trend alignment заавал
   if(InpUseH4Trend && !IsHTFTrendAligned(wBuy, PERIOD_H4, InpH4MAPeriod))
   {
      static datetime lastH4 = 0;
      if(TimeCurrent() - lastH4 > 300)
      { Print("🚫 H4 trend эсрэг — top-level trend тохирохгүй"); lastH4 = TimeCurrent(); }
      return;
   }

   // ★ v3.3: Liquidity sweep шаардах
   if(InpRequireSweep && !HasLiquiditySweep(wBuy))
   {
      static datetime lastSwp = 0;
      if(TimeCurrent() - lastSwp > 300)
      { Print("🚫 Liquidity sweep олдсонгүй — манипуляц нотлогдоогүй"); lastSwp = TimeCurrent(); }
      return;
   }

   // SAFE: Extreme PD блок (20%)
   if(g_tier.pdHigh > 0)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double rng = g_tier.pdHigh - g_tier.pdLow;
      if(wBuy  && ask > g_tier.pdHigh - rng * InpPDExtremeBlock) return;
      if(!wBuy && bid < g_tier.pdLow  + rng * InpPDExtremeBlock) return;
   }

   // SAFE: PD alignment заавал — buy discount, sell premium
   if(InpRequirePDAlign && g_tier.eqLine > 0)
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(wBuy  && ask > g_tier.eqLine) return;  // buy зөвхөн discount талд
      if(!wBuy && bid < g_tier.eqLine) return;  // sell зөвхөн premium талд
   }

   bool hasChoch = false, hasBOS = false;
   for(int i = 0; i < MathMin(g_tier.nBrk, 5); i++)
   {
      if(g_tier.mtfBrks[i].isBullish == wBuy)
      {
         if(!g_tier.mtfBrks[i].isBOS) hasChoch = true;
         if(g_tier.mtfBrks[i].isBOS) hasBOS = true;
      }
   }
   if(!hasChoch && !hasBOS) return;

   for(int i = 0; i < g_tier.nOB; i++)
   {
      if(g_tier.mtfOBs[i].isBullish == wBuy && g_tier.mtfOBs[i].isValid)
      {
         // ★ v3.3: OB нас шалгах (хэт шинэ/хуучин биш)
         int obAge = g_tier.mtfOBs[i].barIdx;
         if(obAge < InpMinOBAgeBars || obAge > InpMaxOBAgeBars) continue;

         g_tier.m5Ready = true;
         g_tier.activeOB = g_tier.mtfOBs[i];

         ENUM_SMC_SETUP sType = hasChoch ? SMC_CHOCH_OB : SMC_BOS_OB;
         string reason = (hasChoch ? "CHoCH+OB" : "BOS+OB");
         reason += wBuy ? " Buy" : " Sell";

         g_tier.setup.valid   = false;
         g_tier.setup.isBuy   = wBuy;
         g_tier.setup.type    = sType;
         g_tier.setup.obTop   = g_tier.activeOB.top;
         g_tier.setup.obBot   = g_tier.activeOB.bottom;
         g_tier.setup.reason  = reason;

         Print("📋 M5 READY: ", reason, " OB=[",
               DoubleToString(g_tier.activeOB.bottom, _Digits), "-",
               DoubleToString(g_tier.activeOB.top, _Digits), "]");
         return;
      }
   }
}

//+------------------------------------------------------------------+
//|  TIER 3: M1 ENTRY                                                  |
//+------------------------------------------------------------------+
void CheckM1Entry()
{
   g_tier.setup.valid = false;
   if(!g_tier.m5Ready) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   bool wBuy  = g_tier.setup.isBuy;
   double price = wBuy ? ask : bid;

   // ═══ SL HUNT path ═══
   if(g_isSLHuntSetup)
   {
      // Үнэ заавал sweepLevel-ээс дээш (bull) / доош (sell) байх — reclaim баталгаажуулалт
      if(wBuy && price < g_slHunt.sweepLevel) return;
      if(!wBuy && price > g_slHunt.sweepLevel) return;

      // Entry reclaim-ээс хэт хол гараагүй эсэх
      double distFromReclaim = MathAbs(price - g_slHunt.reclaimPrice);
      if(distFromReclaim > InpMaxChasePips * 10 * pt)
      {
         if(InpDebugBlocks)
         {
            static datetime lastCh1 = 0;
            if(TimeCurrent() - lastCh1 > 120)
            { Print("🚫 SL-Hunt chase: reclaim-аас ", DoubleToString(distFromReclaim/pt, 0), "pt"); lastCh1 = TimeCurrent(); }
         }
         return;
      }

      // M1 momentum confirmation
      if(!HasM1Momentum(wBuy, InpM1ConfirmBars))
      {
         if(InpDebugBlocks)
         {
            static datetime lastM1a = 0;
            if(TimeCurrent() - lastM1a > 60)
            { Print("⏸ SL-Hunt: M1 momentum дутуу"); lastM1a = TimeCurrent(); }
         }
         return;
      }

      // SL — sweep extreme-ийн ард буфер
      double slBase = wBuy ? g_slHunt.sweepExtreme - InpSLHuntSLBufPips * 10 * pt
                           : g_slHunt.sweepExtreme + InpSLHuntSLBufPips * 10 * pt;

      BuildSetup(wBuy, g_tier.setup.type, price, slBase, g_tier.activeOB,
                 g_tier.setup.reason + " @M1", pt);

      if(g_tier.setup.valid)
         Print("🎯 SL HUNT ENTRY: ", g_tier.setup.reason,
               " Entry=", DoubleToString(price, _Digits),
               " SL=", DoubleToString(slBase, _Digits));
      return;
   }

   // ═══ OB RETEST path ═══
   // OB zone шалгах
   if(price < g_tier.activeOB.bottom || price > g_tier.activeOB.top)
      return;

   // ★ v3.3: Chase хамгаалалт
   double idealEntry = wBuy ? g_tier.activeOB.top : g_tier.activeOB.bottom;
   double chaseDist = MathAbs(price - idealEntry);
   if(chaseDist > InpMaxChasePips * 10 * pt)
   {
      static datetime lastChase = 0;
      if(TimeCurrent() - lastChase > 120)
      { Print("🚫 Chase: ideal-аас ", DoubleToString(chaseDist/pt, 0), "pt хол"); lastChase = TimeCurrent(); }
      return;
   }

   // ★ v3.3: M5 rejection candle шаардах
   if(InpRequireRejection && !HasM5Rejection(wBuy))
   {
      if(InpDebugBlocks)
      {
         static datetime lastRej = 0;
         if(TimeCurrent() - lastRej > 60)
         { Print("⏸ M1: M5 rejection candle алга"); lastRej = TimeCurrent(); }
      }
      return;
   }

   if(!HasM1Momentum(wBuy, InpM1ConfirmBars))
   {
      if(InpDebugBlocks)
      {
         static datetime lastMom = 0;
         if(TimeCurrent() - lastMom > 60)
         { Print("⏸ M1: momentum confirm дутуу"); lastMom = TimeCurrent(); }
      }
      return;
   }

   double slBase;
   if(InpUseStructuralSL)
   {
      double structSL = GetStructuralSL(wBuy);
      double obSL     = wBuy ? g_tier.activeOB.bottom : g_tier.activeOB.top;
      slBase = wBuy ? MathMin(structSL, obSL) : MathMax(structSL, obSL);
   }
   else
      slBase = wBuy ? g_tier.activeOB.bottom : g_tier.activeOB.top;

   BuildSetup(wBuy, g_tier.setup.type, price, slBase, g_tier.activeOB,
              g_tier.setup.reason + " @M1", pt);

   if(g_tier.setup.valid)
      Print("🎯 M1 TRIGGER: ", g_tier.setup.reason,
            " Entry=", DoubleToString(price, _Digits),
            " SL=", DoubleToString(slBase, _Digits),
            " (Reject+Sweep+H1+H4 pass)");
}

//+------------------------------------------------------------------+
//|  OB collector (M5)                                                 |
//+------------------------------------------------------------------+
void CollectOBs(MqlRates &r[], int n)
{
   ArrayResize(g_tier.mtfOBs, 0);
   g_tier.nOB = 0;

   for(int i = 2; i < MathMin(n - 1, 100) && g_tier.nOB < MAX_OB; i++)
   {
      if(r[i].close < r[i].open)
      {
         bool imp = false;
         for(int j = i-1; j >= MathMax(0, i-4); j--)
            if(r[j].close > r[j].open && r[j].high > r[i].high) { imp = true; break; }
         if(imp)
         {
            SOBZone ob;
            ob.top = MathMax(r[i].open, r[i].high);
            ob.bottom = r[i].close;
            ob.timeStart = r[i].time;
            ob.isBullish = true; ob.isValid = true; ob.barIdx = i;
            for(int j = i-1; j >= 1; j--)
               if(r[j].low < ob.bottom) { ob.isValid = false; break; }
            if(ob.isValid) { ArrayResize(g_tier.mtfOBs, g_tier.nOB+1); g_tier.mtfOBs[g_tier.nOB++] = ob; }
         }
      }
      if(r[i].close > r[i].open)
      {
         bool imp = false;
         for(int j = i-1; j >= MathMax(0, i-4); j--)
            if(r[j].close < r[j].open && r[j].low < r[i].low) { imp = true; break; }
         if(imp)
         {
            SOBZone ob;
            ob.top = MathMax(r[i].close, r[i].high);
            ob.bottom = MathMin(r[i].open, r[i].low);
            ob.timeStart = r[i].time;
            ob.isBullish = false; ob.isValid = true; ob.barIdx = i;
            for(int j = i-1; j >= 1; j--)
               if(r[j].high > ob.top) { ob.isValid = false; break; }
            if(ob.isValid) { ArrayResize(g_tier.mtfOBs, g_tier.nOB+1); g_tier.mtfOBs[g_tier.nOB++] = ob; }
         }
      }
   }
}

//+------------------------------------------------------------------+
void CollectBreaks(MqlRates &r[], int n)
{
   ArrayResize(g_tier.mtfBrks, 0);
   g_tier.nBrk = 0;
   if(g_tier.nMTF < 3) return;

   int trend = 0;
   double prevHP = 0, prevLP = 0;
   int prevHB = -1, prevLB = -1;
   int nP = g_tier.nMTF;

   for(int s = nP - 1; s >= 0 && g_tier.nBrk < 20; s--)
   {
      if(g_tier.mtfPivots[s].isHigh)
      {
         if(prevHB >= 0 && g_tier.mtfPivots[s].label == 0)
         {
            int bb = -1;
            for(int j = prevHB - 1; j >= g_tier.mtfPivots[s].barIdx; j--)
               if(j < n && r[j].close > prevHP) { bb = j; break; }
            if(bb >= 0)
            {
               SBreakEvent b;
               b.price = prevHP; b.time = r[bb].time;
               b.isBullish = true; b.isBOS = (trend == 1); b.barIdx = bb;
               ArrayResize(g_tier.mtfBrks, g_tier.nBrk+1);
               g_tier.mtfBrks[g_tier.nBrk++] = b;
            }
            trend = 1;
         }
         prevHP = g_tier.mtfPivots[s].price; prevHB = g_tier.mtfPivots[s].barIdx;
      }
      else
      {
         if(prevLB >= 0 && g_tier.mtfPivots[s].label == 3)
         {
            int bb = -1;
            for(int j = prevLB - 1; j >= g_tier.mtfPivots[s].barIdx; j--)
               if(j < n && r[j].close < prevLP) { bb = j; break; }
            if(bb >= 0)
            {
               SBreakEvent b;
               b.price = prevLP; b.time = r[bb].time;
               b.isBullish = false; b.isBOS = (trend == 2); b.barIdx = bb;
               ArrayResize(g_tier.mtfBrks, g_tier.nBrk+1);
               g_tier.mtfBrks[g_tier.nBrk++] = b;
            }
            trend = 2;
         }
         prevLP = g_tier.mtfPivots[s].price; prevLB = g_tier.mtfPivots[s].barIdx;
      }
   }
}

//+------------------------------------------------------------------+
//|  BUILD SETUP (SAFE: min SL, confluence)                            |
//+------------------------------------------------------------------+
void BuildSetup(bool isBuy, ENUM_SMC_SETUP type,
                double entry, double slBase, SOBZone &ob,
                string reason, double pt)
{
   double sl = isBuy ? (slBase - InpSLBuffer * 10 * pt)
                     : (slBase + InpSLBuffer * 10 * pt);
   double slDist = MathAbs(entry - sl);

   // SAFE: min SL distance шалгалт (stop hunt хамгаалалт)
   if(slDist < InpMinSLPoints * pt)
   {
      Print("⚠ SL too tight: ", DoubleToString(slDist/pt, 0), "pt < min ",
            InpMinSLPoints, "pt. Skip.");
      return;
   }

   double dir = isBuy ? 1.0 : -1.0;

   g_tier.setup.valid   = true;
   g_tier.setup.isBuy   = isBuy;
   g_tier.setup.type    = type;
   g_tier.setup.entry   = entry;
   g_tier.setup.sl      = sl;
   g_tier.setup.obTop   = ob.top;
   g_tier.setup.obBot   = ob.bottom;
   g_tier.setup.reason  = reason;
   g_tier.setup.signalTime = TimeCurrent();

   if(InpTPMode == TP_PARTIAL)
   {
      g_tier.setup.tp1 = entry + dir * slDist * InpTP1_RR;
      g_tier.setup.tp2 = entry + dir * slDist * InpTP2_RR;
      g_tier.setup.tp3 = entry + dir * slDist * InpTP3_RR;
   }
   else
   {
      g_tier.setup.tp1 = entry + dir * slDist * InpSingleTP_RR;
      g_tier.setup.tp2 = 0; g_tier.setup.tp3 = 0;
   }

   g_tier.setup.confluence = CalcConf(isBuy, entry);
   if(g_tier.setup.confluence < InpMinConfluence)
   {
      Print("⚠ Confluence low: ", g_tier.setup.confluence, "/", InpMinConfluence, ". Skip.");
      g_tier.setup.valid = false;
   }
}

int CalcConf(bool isBuy, double price)
{
   int s = 0;
   if((isBuy && g_tier.bias == 1) || (!isBuy && g_tier.bias == 2)) s++;
   if(isBuy  && price < g_tier.eqLine)  s++;
   if(!isBuy && price > g_tier.eqLine)  s++;
   if(isBuy  && price < g_tier.discTop) s++;
   if(!isBuy && price > g_tier.premBot) s++;
   s++;  // setup олдсон
   if(IsGoodSession()) s++;
   if(IsSpreadOK())    s++;  // SAFE: spread good = +1
   return s;
}

//+------------------------------------------------------------------+
//|  ENTRY (SAFE: spread re-check)                                     |
//+------------------------------------------------------------------+
void ExecuteEntry(SSetup &setup)
{
   if(!setup.valid) return;

   if(CountMyPositions() > 0 || CountMyOrders() > 0)
   {
      Print("⚠ Өмнөх арилжаа нээлттэй — шинэ entry цуцлав");
      return;
   }

   // SAFE: entry-ийн өмнө spread дахин шалгах
   if(!IsSpreadOK())
   {
      Print("⚠ Spread хэт өндөр entry-ийн агшинд. Цуцлав.");
      return;
   }

   double lot = CalcLot(setup.entry, setup.sl);
   if(lot <= 0) return;

   double sl = NormalizeDouble(setup.sl, _Digits);
   double tp = NormalizeDouble(setup.tp1, _Digits);
   string cmt = "SMCv3S_" + (setup.type == SMC_CHOCH_OB ? "CHoCH" : "BOS");

   bool ok = setup.isBuy ?
      g_trade.Buy(lot, _Symbol, 0, sl, tp, cmt) :
      g_trade.Sell(lot, _Symbol, 0, sl, tp, cmt);

   if(ok)
   {
      g_todayTrades++;
      g_waitingForClose = true;
      setup.valid = false;
      g_tier.m5Ready = false;
      Print("✅ ", setup.reason, " Lot=", lot, " SL=", sl, " TP=", tp,
            " Conf=", setup.confluence);
      Alert("SMC SAFE: ", setup.reason, " @ ", setup.entry);
      if(InpDrawHistory) DrawTradeMarker(setup);
   }
   else
      Print("❌ ", g_trade.ResultRetcodeDescription());
}

void ManualEntry(bool isBuy)
{
   if(g_tier.m5Ready && g_tier.setup.isBuy == isBuy)
   {
      double price = isBuy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                           : SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      double slBase = isBuy ? g_tier.activeOB.bottom : g_tier.activeOB.top;
      BuildSetup(isBuy, g_tier.setup.type, price, slBase, g_tier.activeOB,
                 "MANUAL " + (isBuy ? "Buy" : "Sell"), pt);
      if(g_tier.setup.valid)
         ExecuteEntry(g_tier.setup);
   }
   else
      Print("⚠ M5 дээр тохирох setup олдсонгүй");
}

//+------------------------------------------------------------------+
double CalcLot(double entry, double sl)
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk = bal * InpRiskPct / 100.0;
   double dist = MathAbs(entry - sl);
   if(dist < _Point) return 0;

   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts == 0 || tv == 0) return 0;

   double lot = risk / (dist / ts * tv);
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   lot = MathFloor(lot / st) * st;
   lot = MathMax(mn, MathMin(mx, lot));
   if(lot > InpMaxLotSize) lot = InpMaxLotSize;

   if(InpReduceAfterLoss && g_lossMultiplier < 1.0)
   {
      lot = lot * g_lossMultiplier;
      lot = MathFloor(lot / st) * st;
      lot = MathMax(mn, lot);
      Print("⚠ Lot reduced (x", DoubleToString(g_lossMultiplier,2), "): ",
            g_consecLoss, " consec loss");
   }

   Print("📐 Lot: risk$=", DoubleToString(risk,2), " dist=",
         DoubleToString(dist/_Point,0), "pt → ", DoubleToString(lot,2));
   return NormalizeDouble(lot, 2);
}

//+------------------------------------------------------------------+
//|  POSITION MGT — TP1-д SL→BE автоматаар                            |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Magic() != InpMagic || g_pos.Symbol() != _Symbol) continue;

      double op = g_pos.PriceOpen();
      double cp = g_pos.PriceCurrent();
      double sl = g_pos.StopLoss();
      double tp = g_pos.TakeProfit();
      double vol = g_pos.Volume();
      ulong  tk = g_pos.Ticket();
      bool isBuy = (g_pos.PositionType() == POSITION_TYPE_BUY);

      double slD = MathAbs(op - sl);
      if(slD < _Point) continue;
      double prof = isBuy ? (cp - op) : (op - cp);
      double rr = prof / slD;

      double minV = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);

      if(InpTPMode == TP_PARTIAL)
      {
         if(rr >= InpTP1_RR && vol > minV * 1.5)
         {
            double cv = NormalizeDouble(vol * InpTP1_Pct / 100.0, 2);
            cv = MathMax(minV, cv);
            if(cv < vol)
            {
               g_trade.PositionClosePartial(tk, cv);
               // SAFE: SL-г breakeven + 2pip болгоно (зөвхөн биш, +profit lock)
               double bePlus = isBuy ? op + 2 * 10 * _Point : op - 2 * 10 * _Point;
               g_trade.PositionModify(tk, NormalizeDouble(bePlus, _Digits), tp);
               Print("📊 TP1: closed ", cv, " lots, SL→BE+2pip");
            }
         }
         else if(rr >= InpTP2_RR && vol > minV * 1.2)
         {
            double cv = NormalizeDouble(vol * InpTP2_Pct / (100.0 - InpTP1_Pct), 2);
            cv = MathMax(minV, cv);
            if(cv < vol) { g_trade.PositionClosePartial(tk, cv); Print("📊 TP2: closed ", cv); }
         }
         // TP3-с дээш: trailing
         if(rr >= InpTP3_RR)
         {
            double trail = InpTrailStep * 10 * _Point;
            double newSL = isBuy ? cp - trail : cp + trail;
            if((isBuy && newSL > sl + _Point) || (!isBuy && newSL < sl - _Point))
               g_trade.PositionModify(tk, NormalizeDouble(newSL, _Digits), tp);
         }
      }
      else
      {
         if(rr >= InpTrailStart_RR)
         {
            double trail = InpTrailStep * 10 * _Point;
            double newSL = isBuy ? cp - trail : cp + trail;
            if((isBuy && newSL > sl + _Point) || (!isBuy && newSL < sl - _Point))
               g_trade.PositionModify(tk, NormalizeDouble(newSL, _Digits), tp);
         }
      }
   }
}

//+------------------------------------------------------------------+
int CollectPivots(MqlRates &r[], int n, int pLen, SPivot &p[])
{
   ArrayResize(p, 0);
   int c = 0;
   for(int i = pLen; i < n - pLen && c < MAX_PIVOTS; i++)
   {
      bool isH = true, isL = true;
      for(int j = 1; j <= pLen; j++)
      {
         if(r[i].high <= r[i-j].high || r[i].high <= r[i+j].high) isH = false;
         if(r[i].low  >= r[i-j].low  || r[i].low  >= r[i+j].low)  isL = false;
         if(!isH && !isL) break;
      }
      if(isH) { ArrayResize(p,c+1); p[c].barIdx=i; p[c].price=r[i].high; p[c].isHigh=true; p[c].label=-1; p[c].time=r[i].time; c++; }
      if(isL) { ArrayResize(p,c+1); p[c].barIdx=i; p[c].price=r[i].low;  p[c].isHigh=false; p[c].label=-1; p[c].time=r[i].time; c++; }
   }
   return c;
}

void ClassifyPivots(SPivot &p[], int nP)
{
   double lH = 0, lL = 0;
   bool hH = false, hL = false;
   for(int s = nP-1; s >= 0; s--)
   {
      if(p[s].isHigh)
      {
         if(hH) p[s].label = (p[s].price > lH) ? 0 : 2;
         lH = p[s].price; hH = true;
      }
      else
      {
         if(hL) p[s].label = (p[s].price > lL) ? 1 : 3;
         lL = p[s].price; hL = true;
      }
   }
}

//+------------------------------------------------------------------+
//|  SAFETY + NEW FILTERS                                              |
//+------------------------------------------------------------------+
bool SafetyOK()
{
   if(g_todayTrades >= InpMaxTradesDay) return false;
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(g_accountStart > 0 && (g_accountStart - bal) / g_accountStart * 100.0 >= InpMaxDailyLoss) return false;
   if(InpSessionFilter && !IsGoodSession()) return false;
   if(InpNoFriday && IsFriday()) return false;
   if(InpNoMondayAM && IsMondayMorning()) return false;

   if(TimeCurrent() < g_cooldownUntil)
   {
      static datetime lastCoolMsg = 0;
      if(TimeCurrent() - lastCoolMsg > 300)
      {
         Print("⏸ COOLDOWN: ", g_consecLoss, " consec loss. Until ",
               TimeToString(g_cooldownUntil));
         lastCoolMsg = TimeCurrent();
      }
      return false;
   }

   if(InpNewsFilter && IsNewsTime())
   {
      static datetime lastNewsMsg = 0;
      if(TimeCurrent() - lastNewsMsg > 300)
      {
         Print("📰 Мэдээний цагт арилжаа хийхгүй!");
         lastNewsMsg = TimeCurrent();
      }
      return false;
   }

   if(!IsSpreadOK())
   {
      static datetime lastSprMsg = 0;
      if(TimeCurrent() - lastSprMsg > 300)
      {
         long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
         Print("💰 Spread өндөр: ", spread, " > ", InpMaxSpreadPts, " point");
         lastSprMsg = TimeCurrent();
      }
      return false;
   }

   if(InpUseATRFilter && !IsATROK())
   {
      static datetime lastAtrMsg = 0;
      if(TimeCurrent() - lastAtrMsg > 300)
      {
         Print("📊 ATR volatility filter: хэт нам эсвэл хэт үймээнтэй");
         lastAtrMsg = TimeCurrent();
      }
      return false;
   }

   return true;
}

bool IsGoodSession()
{
   if(!InpSessionFilter) return true;
   MqlDateTime dt; TimeGMT(dt);
   return (dt.hour >= InpSessionStart && dt.hour <= InpSessionEnd);
}

bool IsFriday()
{
   MqlDateTime dt; TimeGMT(dt);
   return (dt.day_of_week == 5);
}

bool IsMondayMorning()
{
   MqlDateTime dt; TimeGMT(dt);
   return (dt.day_of_week == 1 && dt.hour < 10);
}

bool IsSpreadOK()
{
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   return (spread <= InpMaxSpreadPts);
}

bool IsATROK()
{
   if(!InpUseATRFilter) return true;

   // Cache: 1 минутад нэг тооцоолно
   if(TimeCurrent() - g_atrLastCalc < 60 && g_atrAvg > 0)
   {
      double curATR = iATR_Current();
      if(curATR <= 0) return true;
      double minA = g_atrAvg * InpATRMinMult;
      double maxA = g_atrAvg * InpATRMaxMult;
      return (curATR >= minA && curATR <= maxA);
   }

   int handle = iATR(_Symbol, InpMTF, InpATRPeriod);
   if(handle == INVALID_HANDLE) return true;

   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, 0, 50, buf) < 50) { IndicatorRelease(handle); return true; }

   double sum = 0;
   for(int i = 1; i < 50; i++) sum += buf[i];
   g_atrAvg = sum / 49.0;
   double current = buf[0];
   g_atrLastCalc = TimeCurrent();
   IndicatorRelease(handle);

   double minATR = g_atrAvg * InpATRMinMult;
   double maxATR = g_atrAvg * InpATRMaxMult;
   return (current >= minATR && current <= maxATR);
}

double iATR_Current()
{
   int handle = iATR(_Symbol, InpMTF, InpATRPeriod);
   if(handle == INVALID_HANDLE) return 0;
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, 0, 1, buf) < 1) { IndicatorRelease(handle); return 0; }
   double v = buf[0];
   IndicatorRelease(handle);
   return v;
}

//+------------------------------------------------------------------+
//|  v3.3 COUNTER-TREND PROTECTION HELPERS                            |
//+------------------------------------------------------------------+

// H1/H4 trend confirmation — MA slope + price position
bool IsHTFTrendAligned(bool wantBull, ENUM_TIMEFRAMES tf, int maPeriod)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, tf, 0, maPeriod + 20, r);
   if(n < maPeriod + 5) return true; // Өгөгдөл хангалтгүй бол true буцаана

   // MA тооцоолох (одоогийн ба 5 лаагийн өмнөх)
   double maNow = 0, maPrev = 0;
   for(int i = 0; i < maPeriod; i++) maNow  += r[i].close;
   for(int i = 5; i < maPeriod + 5; i++) maPrev += r[i].close;
   maNow  /= maPeriod;
   maPrev /= maPeriod;

   // MA slope (өсөлт/бууралт)
   bool maRising = (maNow > maPrev);
   bool priceAbove = (r[0].close > maNow);

   if(wantBull) return (maRising && priceAbove);
   else         return (!maRising && !priceAbove);
}

// M5 rejection candle шалгах (OB zone дээр)
bool HasM5Rejection(bool wantBull)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, InpMTF, 0, 5, r) < 3) return false;

   // Сүүлд хаагдсан M5 лаа (index 1)
   double body = MathAbs(r[1].close - r[1].open);
   if(body < _Point) body = _Point;

   if(wantBull)
   {
      // Bullish rejection: доош урт wick, bullish close, OB дотор
      double lowerWick = MathMin(r[1].open, r[1].close) - r[1].low;
      double upperWick = r[1].high - MathMax(r[1].open, r[1].close);
      bool bullClose = (r[1].close > r[1].open);
      bool wickOK = (lowerWick > body * InpMinWickRatio) && (lowerWick > upperWick);
      bool touchedOB = (r[1].low <= g_tier.activeOB.top && r[1].low >= g_tier.activeOB.bottom - (g_tier.activeOB.top - g_tier.activeOB.bottom));
      return (bullClose && wickOK && touchedOB);
   }
   else
   {
      double lowerWick = MathMin(r[1].open, r[1].close) - r[1].low;
      double upperWick = r[1].high - MathMax(r[1].open, r[1].close);
      bool bearClose = (r[1].close < r[1].open);
      bool wickOK = (upperWick > body * InpMinWickRatio) && (upperWick > lowerWick);
      bool touchedOB = (r[1].high >= g_tier.activeOB.bottom && r[1].high <= g_tier.activeOB.top + (g_tier.activeOB.top - g_tier.activeOB.bottom));
      return (bearClose && wickOK && touchedOB);
   }
}

// OB насыг тоолох (M5 лаа)
int GetOBAgeBars()
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, InpMTF, 0, InpMaxOBAgeBars + 5, r);
   if(n < 2) return 0;
   for(int i = 0; i < n; i++)
      if(r[i].time <= g_tier.activeOB.timeStart) return i;
   return n;
}

// Liquidity sweep шалгах: CHoCH-ийн өмнө wick өмнөх swing low/high-аас давсан эсэх
bool HasLiquiditySweep(bool wantBull)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, InpMTF, 0, InpSweepLookback + 10, r);
   if(n < InpSweepLookback + 2) return false;

   double pt = _Point;
   double minSweep = InpSweepMinPips * 10 * pt;

   if(wantBull)
   {
      // Buy-д: сүүлийн 5-15 лаанд хамгийн доод low олоод, түүнээс доош wick гарсан эсэх
      double swingLow = DBL_MAX;
      int swingIdx = -1;
      for(int i = 5; i < InpSweepLookback; i++)
         if(r[i].low < swingLow) { swingLow = r[i].low; swingIdx = i; }
      if(swingIdx < 0) return false;

      // Сүүлийн 5 лаанд swingLow-оос доош wick гарсан эсэх
      for(int i = 0; i < 5; i++)
         if(r[i].low < swingLow - minSweep && r[i].close > swingLow) return true;
      return false;
   }
   else
   {
      double swingHigh = -DBL_MAX;
      int swingIdx = -1;
      for(int i = 5; i < InpSweepLookback; i++)
         if(r[i].high > swingHigh) { swingHigh = r[i].high; swingIdx = i; }
      if(swingIdx < 0) return false;

      for(int i = 0; i < 5; i++)
         if(r[i].high > swingHigh + minSweep && r[i].close < swingHigh) return true;
      return false;
   }
}

// Structural SL — M5 swing low/high дээр тавих (OB зааг биш)
double GetStructuralSL(bool isBuy)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, InpMTF, 0, InpStructLookback + 5, r);
   if(n < InpStructLookback) return 0;

   if(isBuy)
   {
      // Хамгийн доод low — сүүлийн N M5 лаа
      double lo = DBL_MAX;
      for(int i = 0; i < InpStructLookback; i++)
         if(r[i].low < lo) lo = r[i].low;
      return lo;
   }
   else
   {
      double hi = -DBL_MAX;
      for(int i = 0; i < InpStructLookback; i++)
         if(r[i].high > hi) hi = r[i].high;
      return hi;
   }
}

// M1 олон лааны дараалсан баталгаажуулалт
bool HasM1Momentum(bool wantBull, int bars)
{
   if(bars <= 0) return true;
   MqlRates m1[];
   ArraySetAsSeries(m1, true);
   if(CopyRates(_Symbol, InpLTF, 0, bars + 2, m1) < bars + 1) return false;

   for(int i = 1; i <= bars; i++)
   {
      if(wantBull && m1[i].close <= m1[i].open) return false;
      if(!wantBull && m1[i].close >= m1[i].open) return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//|  SL HUNT DETECTION (v3.4)                                          |
//|  Pattern: Price wick beyond swing low/high, then close back inside |
//|  This is "stop hunt" - liquidity grab → reversal                  |
//+------------------------------------------------------------------+
bool DetectSLHunt(bool wantBull, SSLHunt &hunt)
{
   hunt.valid = false;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int lookback = InpSLHuntLookback + InpSLHuntScanBars + 5;
   int n = CopyRates(_Symbol, InpMTF, 0, lookback, r);
   if(n < InpSLHuntLookback + 2) return false;

   double pt = _Point;
   double minSweep = InpSLHuntMinPips * 10 * pt;
   double maxSweep = InpSLHuntMaxPips * 10 * pt;

   if(wantBull)
   {
      // 1. Swing low олох — scan range-аас гадна (хамгийн доод)
      double swingLow = DBL_MAX;
      int swingIdx = -1;
      for(int i = InpSLHuntScanBars + 2; i < InpSLHuntLookback; i++)
      {
         if(r[i].low < swingLow)
         {
            swingLow = r[i].low;
            swingIdx = i;
         }
      }
      if(swingIdx < 0) return false;

      // 2. Сүүлийн N лаанд sweep хайх (i=1-с эхэлнэ, r[0] хоосон бар)
      for(int i = 1; i <= InpSLHuntScanBars && i < n; i++)
      {
         double wickDepth = swingLow - r[i].low;
         if(wickDepth < minSweep) continue;     // хангалттай гүн биш
         if(wickDepth > maxSweep) continue;     // хэт хол — flash biш

         // Close нь swing low-оос дээш (reclaim)
         double bodyRange = MathAbs(r[i].close - r[i].low);
         double totalRange = r[i].high - r[i].low;
         if(totalRange < pt) continue;

         // Close нь wick-ийн дээд хэсэгт (50%+)
         double closePos = (r[i].close - r[i].low) / totalRange;
         if(closePos < InpSLHuntCloseBack) continue;
         if(r[i].close <= swingLow) continue;   // заавал reclaim

         hunt.valid = true;
         hunt.isBuy = true;
         hunt.sweepLevel = swingLow;
         hunt.sweepExtreme = r[i].low;
         hunt.reclaimPrice = r[i].close;
         hunt.sweepTime = r[i].time;
         hunt.sweepBarIdx = i;
         return true;
      }
   }
   else
   {
      // Sell: swing high sweep
      double swingHigh = -DBL_MAX;
      int swingIdx = -1;
      for(int i = InpSLHuntScanBars + 2; i < InpSLHuntLookback; i++)
      {
         if(r[i].high > swingHigh)
         {
            swingHigh = r[i].high;
            swingIdx = i;
         }
      }
      if(swingIdx < 0) return false;

      for(int i = 1; i <= InpSLHuntScanBars && i < n; i++)
      {
         double wickHeight = r[i].high - swingHigh;
         if(wickHeight < minSweep) continue;
         if(wickHeight > maxSweep) continue;

         double totalRange = r[i].high - r[i].low;
         if(totalRange < pt) continue;

         double closePos = (r[i].high - r[i].close) / totalRange;
         if(closePos < InpSLHuntCloseBack) continue;
         if(r[i].close >= swingHigh) continue;

         hunt.valid = true;
         hunt.isBuy = false;
         hunt.sweepLevel = swingHigh;
         hunt.sweepExtreme = r[i].high;
         hunt.reclaimPrice = r[i].close;
         hunt.sweepTime = r[i].time;
         hunt.sweepBarIdx = i;
         return true;
      }
   }
   return false;
}

bool IsNewsTime()
{
   MqlDateTime dt; TimeGMT(dt);
   datetime now = TimeGMT();
   int beforeSec = InpNewsBeforeMin * 60;
   int afterSec  = InpNewsAfterMin * 60;

   if(InpBlockNFP && dt.day_of_week == 5 && dt.day <= 7)
   {
      datetime nfpTime = BuildGMTTime(dt.year, dt.mon, dt.day, 12, 30);
      if(now >= nfpTime - beforeSec && now <= nfpTime + afterSec) return true;
   }

   if(InpBlockFOMC && dt.day_of_week == 3 && dt.day >= 15)
   {
      datetime fomcTime = BuildGMTTime(dt.year, dt.mon, dt.day, 18, 0);
      if(now >= fomcTime - beforeSec && now <= fomcTime + afterSec) return true;
      datetime fomc2 = BuildGMTTime(dt.year, dt.mon, dt.day, 18, 30);
      if(now >= fomc2 - beforeSec && now <= fomc2 + afterSec) return true;
   }

   if(InpBlockCPI && dt.day >= 10 && dt.day <= 15)
   {
      datetime cpiTime = BuildGMTTime(dt.year, dt.mon, dt.day, 12, 30);
      if(now >= cpiTime - beforeSec && now <= cpiTime + afterSec) return true;
   }

   if(InpCustomNewsHour1 >= 0)
   {
      datetime ct1 = BuildGMTTime(dt.year, dt.mon, dt.day, InpCustomNewsHour1, InpCustomNewsMin1);
      if(now >= ct1 - beforeSec && now <= ct1 + afterSec) return true;
   }
   if(InpCustomNewsHour2 >= 0)
   {
      datetime ct2 = BuildGMTTime(dt.year, dt.mon, dt.day, InpCustomNewsHour2, InpCustomNewsMin2);
      if(now >= ct2 - beforeSec && now <= ct2 + afterSec) return true;
   }

   return false;
}

datetime BuildGMTTime(int y, int m, int d, int h, int mn)
{
   MqlDateTime s;
   s.year = y; s.mon = m; s.day = d;
   s.hour = h; s.min = mn; s.sec = 0;
   s.day_of_week = 0; s.day_of_year = 0;
   return StructToTime(s);
}

void CheckTradeHistory()
{
   g_consecLoss = 0;
   g_lossMultiplier = 1.0;

   if(!HistorySelect(TimeCurrent() - 30 * 86400, TimeCurrent())) return;
   int total = HistoryDealsTotal();

   for(int i = total - 1; i >= 0 && i >= total - 20; i--)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT)
                    + HistoryDealGetDouble(ticket, DEAL_SWAP)
                    + HistoryDealGetDouble(ticket, DEAL_COMMISSION);

      if(profit < 0) g_consecLoss++;
      else break;
   }

   if(InpReduceAfterLoss && g_consecLoss >= 1)
   {
      if(g_consecLoss >= 3) g_lossMultiplier = 0.25;
      else if(g_consecLoss >= 2) g_lossMultiplier = 0.50;
      else g_lossMultiplier = 0.75;
      Print("⚡ Consec loss: ", g_consecLoss, " → lot x", g_lossMultiplier);
   }

   if(g_consecLoss >= InpMaxConsecLoss)
   {
      g_cooldownUntil = TimeCurrent() + InpCooldownHours * 3600;
      Print("🛑 ", g_consecLoss, " consec loss! Cooldown активжлаа.");
   }
}

void ResetDaily()
{
   static int ld = -1;
   MqlDateTime dt; TimeCurrent(dt);
   if(dt.day_of_year != ld) { ld = dt.day_of_year; g_todayTrades = 0; g_accountStart = AccountInfoDouble(ACCOUNT_BALANCE); }
}

int CountMyPositions()
{
   int c = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol) c++;
   return c;
}

int CountMyOrders()
{
   int c = 0;
   for(int i = OrdersTotal()-1; i >= 0; i--)
      if(g_order.SelectByIndex(i) && g_order.Magic() == InpMagic && g_order.Symbol() == _Symbol) c++;
   return c;
}

void CloseAll()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
         g_trade.PositionClose(g_pos.Ticket());
   for(int i = OrdersTotal()-1; i >= 0; i--)
      if(g_order.SelectByIndex(i) && g_order.Magic() == InpMagic && g_order.Symbol() == _Symbol)
         g_trade.OrderDelete(g_order.Ticket());
   g_waitingForClose = false;
   g_tier.m5Ready = false;
   Print("🔴 All closed");
}

//+------------------------------------------------------------------+
//|  CHART DRAWING                                                     |
//+------------------------------------------------------------------+
void DrawAll()
{
   ObjectsDeleteAll(0, DRW_PREFIX);
   g_seq = 0;

   if(InpDrawSwings)
   {
      for(int i = 0; i < MathMin(g_tier.nMTF, 20); i++)
      {
         if(g_tier.mtfPivots[i].label < 0) continue;
         string lbl = ""; color clr = InpPanelText;
         switch(g_tier.mtfPivots[i].label)
         {
            case 0: lbl="HH"; clr=InpBullClr; break;
            case 1: lbl="HL"; clr=InpBullClr; break;
            case 2: lbl="LH"; clr=InpBearClr; break;
            case 3: lbl="LL"; clr=InpBearClr; break;
            default: continue;
         }
         string nm = DRW_PREFIX + "S" + IntegerToString(g_seq++);
         ObjectCreate(0, nm, OBJ_TEXT, 0, g_tier.mtfPivots[i].time, g_tier.mtfPivots[i].price);
         ObjectSetString(0, nm, OBJPROP_TEXT, lbl);
         ObjectSetString(0, nm, OBJPROP_FONT, "Arial Bold");
         ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
         ObjectSetInteger(0, nm, OBJPROP_ANCHOR, g_tier.mtfPivots[i].isHigh ? ANCHOR_LOWER : ANCHOR_UPPER);
      }
   }

   if(InpDrawBreaks)
   {
      for(int i = 0; i < g_tier.nBrk; i++)
      {
         datetime t1 = g_tier.mtfBrks[i].time - PeriodSeconds(InpMTF) * 10;
         datetime t2 = g_tier.mtfBrks[i].time + PeriodSeconds(InpMTF) * 5;
         color lc = g_tier.mtfBrks[i].isBOS ? InpBosClr : InpChochClr;

         string ln = DRW_PREFIX + "B" + IntegerToString(g_seq++);
         ObjectCreate(0, ln, OBJ_TREND, 0, t1, g_tier.mtfBrks[i].price, t2, g_tier.mtfBrks[i].price);
         ObjectSetInteger(0, ln, OBJPROP_COLOR, lc);
         ObjectSetInteger(0, ln, OBJPROP_WIDTH, g_tier.mtfBrks[i].isBOS ? 1 : 2);
         ObjectSetInteger(0, ln, OBJPROP_STYLE, g_tier.mtfBrks[i].isBOS ? STYLE_DASH : STYLE_SOLID);
         ObjectSetInteger(0, ln, OBJPROP_RAY_RIGHT, false);

         string lb = DRW_PREFIX + "BL" + IntegerToString(g_seq++);
         ObjectCreate(0, lb, OBJ_TEXT, 0, t2, g_tier.mtfBrks[i].price);
         ObjectSetString(0, lb, OBJPROP_TEXT, g_tier.mtfBrks[i].isBOS ? "BOS" : "CHoCH");
         ObjectSetString(0, lb, OBJPROP_FONT, "Arial Bold");
         ObjectSetInteger(0, lb, OBJPROP_FONTSIZE, 7);
         ObjectSetInteger(0, lb, OBJPROP_COLOR, lc);
      }
   }

   if(InpDrawOB)
   {
      for(int i = 0; i < g_tier.nOB; i++)
      {
         string nm = DRW_PREFIX + "OB" + IntegerToString(g_seq++);
         datetime t2 = TimeCurrent() + PeriodSeconds(InpMTF) * 10;
         ObjectCreate(0, nm, OBJ_RECTANGLE, 0, g_tier.mtfOBs[i].timeStart, g_tier.mtfOBs[i].top, t2, g_tier.mtfOBs[i].bottom);
         color oc = g_tier.mtfOBs[i].isBullish ? InpBullClr : InpBearClr;
         ObjectSetInteger(0, nm, OBJPROP_COLOR, oc);
         ObjectSetInteger(0, nm, OBJPROP_FILL, true);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);

         string lb = DRW_PREFIX + "OBL" + IntegerToString(g_seq++);
         ObjectCreate(0, lb, OBJ_TEXT, 0, g_tier.mtfOBs[i].timeStart, g_tier.mtfOBs[i].top);
         ObjectSetString(0, lb, OBJPROP_TEXT, g_tier.mtfOBs[i].isBullish ? "Bull OB" : "Bear OB");
         ObjectSetString(0, lb, OBJPROP_FONT, "Arial");
         ObjectSetInteger(0, lb, OBJPROP_FONTSIZE, 7);
         ObjectSetInteger(0, lb, OBJPROP_COLOR, oc);
      }
   }

   if(g_tier.m5Ready && InpDrawOB)
   {
      string aN = DRW_PREFIX + "ACTIVE_OB";
      datetime t2 = TimeCurrent() + PeriodSeconds(InpLTF) * 30;
      ObjectCreate(0, aN, OBJ_RECTANGLE, 0, g_tier.activeOB.timeStart, g_tier.activeOB.top, t2, g_tier.activeOB.bottom);
      ObjectSetInteger(0, aN, OBJPROP_COLOR, InpEntryClr);
      ObjectSetInteger(0, aN, OBJPROP_FILL, true);
      ObjectSetInteger(0, aN, OBJPROP_BACK, true);
      ObjectSetInteger(0, aN, OBJPROP_WIDTH, 2);

      string al = DRW_PREFIX + "ACTIVE_LBL";
      ObjectCreate(0, al, OBJ_TEXT, 0, g_tier.activeOB.timeStart, g_tier.activeOB.top);
      ObjectSetString(0, al, OBJPROP_TEXT, "★ M1 ENTRY ZONE ★");
      ObjectSetString(0, al, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, al, OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, al, OBJPROP_COLOR, InpEntryClr);
   }

   if(InpDrawPD && g_tier.pdHigh > 0)
   {
      datetime now = TimeCurrent();
      datetime ago = now - PeriodSeconds(InpHTF) * 30;

      string pN = DRW_PREFIX + "PR";
      ObjectCreate(0, pN, OBJ_RECTANGLE, 0, ago, g_tier.pdHigh, now, g_tier.premBot);
      ObjectSetInteger(0, pN, OBJPROP_COLOR, InpPremClr);
      ObjectSetInteger(0, pN, OBJPROP_FILL, true); ObjectSetInteger(0, pN, OBJPROP_BACK, true);

      string dN = DRW_PREFIX + "DI";
      ObjectCreate(0, dN, OBJ_RECTANGLE, 0, ago, g_tier.discTop, now, g_tier.pdLow);
      ObjectSetInteger(0, dN, OBJPROP_COLOR, InpDiscClr);
      ObjectSetInteger(0, dN, OBJPROP_FILL, true); ObjectSetInteger(0, dN, OBJPROP_BACK, true);

      string eN = DRW_PREFIX + "EQ";
      ObjectCreate(0, eN, OBJ_TREND, 0, ago, g_tier.eqLine, now, g_tier.eqLine);
      ObjectSetInteger(0, eN, OBJPROP_COLOR, InpEqClr);
      ObjectSetInteger(0, eN, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, eN, OBJPROP_RAY_RIGHT, false);

      string pl = DRW_PREFIX + "PRL"; ObjectCreate(0, pl, OBJ_TEXT, 0, now, g_tier.pdHigh);
      ObjectSetString(0, pl, OBJPROP_TEXT, "PREMIUM"); ObjectSetString(0, pl, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, pl, OBJPROP_FONTSIZE, 8); ObjectSetInteger(0, pl, OBJPROP_COLOR, InpPremClr);

      string dl = DRW_PREFIX + "DIL"; ObjectCreate(0, dl, OBJ_TEXT, 0, now, g_tier.pdLow);
      ObjectSetString(0, dl, OBJPROP_TEXT, "DISCOUNT"); ObjectSetString(0, dl, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, dl, OBJPROP_FONTSIZE, 8); ObjectSetInteger(0, dl, OBJPROP_COLOR, InpDiscClr);

      string el = DRW_PREFIX + "EQL"; ObjectCreate(0, el, OBJ_TEXT, 0, now, g_tier.eqLine);
      ObjectSetString(0, el, OBJPROP_TEXT, "EQ 50%"); ObjectSetString(0, el, OBJPROP_FONT, "Arial");
      ObjectSetInteger(0, el, OBJPROP_FONTSIZE, 7); ObjectSetInteger(0, el, OBJPROP_COLOR, InpEqClr);
   }

   if(InpDrawEntry && g_tier.setup.valid)
      DrawEntryLines(g_tier.setup);

   ChartRedraw(0);
}

void DrawEntryLines(SSetup &s)
{
   datetime now = TimeCurrent();
   datetime fut = now + PeriodSeconds(InpLTF) * 60;

   string eN = DRW_PREFIX + "EN";
   ObjectCreate(0, eN, OBJ_TREND, 0, now, s.entry, fut, s.entry);
   ObjectSetInteger(0, eN, OBJPROP_COLOR, InpEntryClr); ObjectSetInteger(0, eN, OBJPROP_WIDTH, 2);
   ObjectSetInteger(0, eN, OBJPROP_RAY_RIGHT, false);

   string el = DRW_PREFIX + "ENL"; ObjectCreate(0, el, OBJ_TEXT, 0, fut, s.entry);
   ObjectSetString(0, el, OBJPROP_TEXT, "▶ ENTRY " + DoubleToString(s.entry, _Digits));
   ObjectSetString(0, el, OBJPROP_FONT, "Arial Bold");
   ObjectSetInteger(0, el, OBJPROP_FONTSIZE, 8); ObjectSetInteger(0, el, OBJPROP_COLOR, InpEntryClr);

   string sN = DRW_PREFIX + "SL";
   ObjectCreate(0, sN, OBJ_TREND, 0, now, s.sl, fut, s.sl);
   ObjectSetInteger(0, sN, OBJPROP_COLOR, InpSLClr); ObjectSetInteger(0, sN, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, sN, OBJPROP_RAY_RIGHT, false);
   string sl2 = DRW_PREFIX + "SLL"; ObjectCreate(0, sl2, OBJ_TEXT, 0, fut, s.sl);
   ObjectSetString(0, sl2, OBJPROP_TEXT, "✖ SL " + DoubleToString(s.sl, _Digits));
   ObjectSetString(0, sl2, OBJPROP_FONT, "Arial"); ObjectSetInteger(0, sl2, OBJPROP_FONTSIZE, 7);
   ObjectSetInteger(0, sl2, OBJPROP_COLOR, InpSLClr);

   string t1 = DRW_PREFIX + "T1";
   ObjectCreate(0, t1, OBJ_TREND, 0, now, s.tp1, fut, s.tp1);
   ObjectSetInteger(0, t1, OBJPROP_COLOR, InpTPClr); ObjectSetInteger(0, t1, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, t1, OBJPROP_RAY_RIGHT, false);
   string tl1 = DRW_PREFIX + "T1L"; ObjectCreate(0, tl1, OBJ_TEXT, 0, fut, s.tp1);
   ObjectSetString(0, tl1, OBJPROP_TEXT, "◎ TP1 " + DoubleToString(s.tp1, _Digits));
   ObjectSetString(0, tl1, OBJPROP_FONT, "Arial"); ObjectSetInteger(0, tl1, OBJPROP_FONTSIZE, 7);
   ObjectSetInteger(0, tl1, OBJPROP_COLOR, InpTPClr);

   if(s.tp2 > 0)
   {
      string t2n = DRW_PREFIX + "T2";
      ObjectCreate(0, t2n, OBJ_TREND, 0, now, s.tp2, fut, s.tp2);
      ObjectSetInteger(0, t2n, OBJPROP_COLOR, InpTPClr); ObjectSetInteger(0, t2n, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, t2n, OBJPROP_RAY_RIGHT, false);
   }
   if(s.tp3 > 0)
   {
      string t3n = DRW_PREFIX + "T3";
      ObjectCreate(0, t3n, OBJ_TREND, 0, now, s.tp3, fut, s.tp3);
      ObjectSetInteger(0, t3n, OBJPROP_COLOR, InpTPClr); ObjectSetInteger(0, t3n, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, t3n, OBJPROP_RAY_RIGHT, false);
   }
}

void DrawTradeMarker(SSetup &s)
{
   string nm = DRW_PREFIX + "TM" + IntegerToString(g_seq++);
   ObjectCreate(0, nm, OBJ_ARROW, 0, s.signalTime, s.entry);
   ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, s.isBuy ? 233 : 234);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, s.isBuy ? InpBullClr : InpBearClr);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, 3);
}

//+------------------------------------------------------------------+
//|  GUI PANEL                                                         |
//+------------------------------------------------------------------+
void CreatePanel()
{
   int x = InpPanelX, y = InpPanelY;
   PRect(PNL_PREFIX + "BG", x, y, 270, 460, InpPanelBG);
   PLbl(PNL_PREFIX + "TIT", x+8, y+6, "🎯 SMC PURE EA v3.4-SLHUNT", InpPanelText, 10, true);
   PLbl(PNL_PREFIX + "SUB", x+8, y+20, "SL Hunt + OB Retest dual entry", C'120,120,140', 7, false);

   PBtn(PNL_PREFIX + "BTN_MODE", x+8, y+36, 254, 22, "MODE: AUTO", InpBtnActive);

   int ly = y + 64;
   PLbl(PNL_PREFIX + "T1H", x+8, ly, "━ M15 Чиглэл ━", C'100,180,220', 8, true);
   PLbl(PNL_PREFIX + "T1B", x+8, ly+14, "Bias: ---", InpPanelText, 9, false);

   ly += 30;
   PLbl(PNL_PREFIX + "T2H", x+8, ly, "━ M5 Баталгаажуулалт ━", C'220,180,100', 8, true);
   PLbl(PNL_PREFIX + "T2S", x+8, ly+14, "CHoCH/BOS: ---", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "T2O", x+8, ly+28, "OB: ---", InpPanelText, 9, false);

   ly += 44;
   PLbl(PNL_PREFIX + "T3H", x+8, ly, "━ M1 Entry ━", C'180,220,100', 8, true);
   PLbl(PNL_PREFIX + "T3S", x+8, ly+14, "Entry: хүлээж байна...", InpPanelText, 9, false);

   ly += 32;
   PLbl(PNL_PREFIX + "ZONE", x+8, ly, "Zone: ---", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "POS",  x+8, ly+14, "Position: NONE", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "DAY",  x+8, ly+28, "Today: 0/2", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "PL",   x+8, ly+42, "P&L: $0.00", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "LOSS", x+8, ly+56, "Loss streak: 0", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "SPRD", x+8, ly+70, "Spread: ---", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "ATR",  x+8, ly+84, "ATR: ---", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "HTF",  x+8, ly+98, "H1/H4: ---", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "SWEEP",x+8, ly+112,"Sweep: ---", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "FILT", x+8, ly+126,"Filters: OK", InpPanelText, 9, false);
   PLbl(PNL_PREFIX + "WAIT", x+8, ly+140,"Status: SCANNING", C'180,180,50', 9, true);

   ly += 158;
   PBtn(PNL_PREFIX + "BTN_BUY",  x+8,   ly, 123, 26, "▲ BUY",  C'0,150,80');
   PBtn(PNL_PREFIX + "BTN_SELL", x+139, ly, 123, 26, "▼ SELL", C'180,40,40');
   ly += 32;
   PBtn(PNL_PREFIX + "BTN_CLOSE", x+8, ly, 254, 24, "CLOSE ALL", C'120,60,60');

   g_panelOK = true;
   ChartRedraw(0);
}

void UpdatePanel()
{
   if(!g_panelOK) return;

   string mt = (g_mode == MODE_AUTO) ? "MODE: ⚡ AUTO" : "MODE: ✋ MANUAL";
   color mc   = (g_mode == MODE_AUTO) ? InpBtnActive : C'200,150,40';
   STxt(PNL_PREFIX + "BTN_MODE", mt);
   ObjectSetInteger(0, PNL_PREFIX + "BTN_MODE", OBJPROP_BGCOLOR, mc);
   ObjectSetInteger(0, PNL_PREFIX + "BTN_MODE", OBJPROP_STATE, false);

   STxt(PNL_PREFIX + "T1B", "Bias: " + g_tier.biasText);
   SClr(PNL_PREFIX + "T1B", g_tier.bias==1 ? InpBullClr : g_tier.bias==2 ? InpBearClr : InpPanelText);

   string brkTxt = "CHoCH/BOS: ";
   if(g_tier.nBrk > 0)
   {
      int chc = 0, bos = 0;
      for(int i = 0; i < g_tier.nBrk; i++) { if(g_tier.mtfBrks[i].isBOS) bos++; else chc++; }
      brkTxt += IntegerToString(chc) + " CHoCH, " + IntegerToString(bos) + " BOS";
   }
   else brkTxt += "scanning...";
   STxt(PNL_PREFIX + "T2S", brkTxt);

   string obTxt = "OB: " + IntegerToString(g_tier.nOB) + " zones";
   if(g_tier.m5Ready) obTxt += " ★ACTIVE★";
   STxt(PNL_PREFIX + "T2O", obTxt);
   SClr(PNL_PREFIX + "T2O", g_tier.m5Ready ? InpEntryClr : InpPanelText);

   if(g_tier.setup.valid)
      STxt(PNL_PREFIX + "T3S", "Entry: " + g_tier.setup.reason +
           " (" + IntegerToString(g_tier.setup.confluence) + "/" +
           IntegerToString(InpMinConfluence) + ")");
   else if(g_tier.m5Ready)
      STxt(PNL_PREFIX + "T3S", "Entry: M1 retest хүлээж байна...");
   else
      STxt(PNL_PREFIX + "T3S", "Entry: M5 setup хүлээж байна...");
   SClr(PNL_PREFIX + "T3S", g_tier.setup.valid ? InpBullClr :
        g_tier.m5Ready ? InpEntryClr : InpPanelText);

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double eq = g_tier.eqLine;
   double pB = g_tier.premBot;
   double dT = g_tier.discTop;
   string zt = "Zone: ";
   if(eq > 0) { if(ask > pB) zt += "PREMIUM ⬆"; else if(ask < dT) zt += "DISCOUNT ⬇"; else zt += "EQ ↔"; }
   else zt += "---";
   STxt(PNL_PREFIX + "ZONE", zt);

   int op = CountMyPositions();
   STxt(PNL_PREFIX + "POS", op > 0 ? "Position: OPEN (" + IntegerToString(op) + ")" : "Position: NONE");
   SClr(PNL_PREFIX + "POS", op > 0 ? InpBullClr : InpPanelText);

   STxt(PNL_PREFIX + "DAY", "Today: " + IntegerToString(g_todayTrades) + "/" + IntegerToString(InpMaxTradesDay));

   double pl = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) && g_pos.Magic() == InpMagic && g_pos.Symbol() == _Symbol)
         pl += g_pos.Profit() + g_pos.Swap() + g_pos.Commission();
   STxt(PNL_PREFIX + "PL", "P&L: $" + DoubleToString(pl, 2));
   SClr(PNL_PREFIX + "PL", pl > 0 ? InpBullClr : pl < 0 ? InpBearClr : InpPanelText);

   string lossStr = "Loss streak: " + IntegerToString(g_consecLoss);
   if(g_lossMultiplier < 1.0) lossStr += " (lot x" + DoubleToString(g_lossMultiplier, 2) + ")";
   STxt(PNL_PREFIX + "LOSS", lossStr);
   SClr(PNL_PREFIX + "LOSS", g_consecLoss >= 2 ? InpBearClr :
        g_consecLoss >= 1 ? C'255,152,0' : InpPanelText);

   // Spread
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   string sprdStr = "Spread: " + IntegerToString(spread) + "pt";
   if(spread > InpMaxSpreadPts) sprdStr += " ⚠";
   STxt(PNL_PREFIX + "SPRD", sprdStr);
   SClr(PNL_PREFIX + "SPRD", spread > InpMaxSpreadPts ? InpBearClr : InpPanelText);

   // ATR
   string atrStr = "ATR: ";
   if(g_atrAvg > 0)
   {
      double curA = iATR_Current();
      atrStr += DoubleToString(curA / _Point, 0) + "pt (avg " +
                DoubleToString(g_atrAvg / _Point, 0) + ")";
      if(!IsATROK()) atrStr += " ⚠";
   }
   else atrStr += "---";
   STxt(PNL_PREFIX + "ATR", atrStr);
   SClr(PNL_PREFIX + "ATR", (g_atrAvg > 0 && !IsATROK()) ? InpBearClr : InpPanelText);

   // ★ v3.3: H1/H4 trend status
   if(g_tier.bias != 0)
   {
      bool wBuy = (g_tier.bias == 1);
      bool h1OK = !InpUseH1Trend || IsHTFTrendAligned(wBuy, PERIOD_H1, InpH1MAPeriod);
      bool h4OK = !InpUseH4Trend || IsHTFTrendAligned(wBuy, PERIOD_H4, InpH4MAPeriod);
      string htfStr = "H1/H4: ";
      htfStr += h1OK ? "✓" : "✗";
      htfStr += " / ";
      htfStr += h4OK ? "✓" : "✗";
      STxt(PNL_PREFIX + "HTF", htfStr);
      SClr(PNL_PREFIX + "HTF", (h1OK && h4OK) ? InpBullClr : InpBearClr);

      // SL Hunt детектор харуулна
      SSLHunt huntCheck;
      bool hasHunt = DetectSLHunt(wBuy, huntCheck);
      string huntStr;
      if(InpUseSLHunt && hasHunt)
         huntStr = "SL Hunt: ✓ " + (wBuy ? "BULL sweep" : "BEAR sweep") +
                   " @" + DoubleToString(huntCheck.sweepLevel, _Digits);
      else if(InpUseSLHunt)
         huntStr = "SL Hunt: scanning...";
      else
         huntStr = "SL Hunt: disabled";
      STxt(PNL_PREFIX + "SWEEP", huntStr);
      SClr(PNL_PREFIX + "SWEEP", hasHunt ? InpBullClr : C'180,180,50');
   }
   else
   {
      STxt(PNL_PREFIX + "HTF", "H1/H4: scanning");
      STxt(PNL_PREFIX + "SWEEP", "Sweep: ---");
   }

   string filtStr = "Filters: ";
   bool blocked = false;
   if(InpNoFriday && IsFriday()) { filtStr += "FRI "; blocked = true; }
   if(InpNoMondayAM && IsMondayMorning()) { filtStr += "MON-AM "; blocked = true; }
   if(InpNewsFilter && IsNewsTime()) { filtStr += "NEWS "; blocked = true; }
   if(TimeCurrent() < g_cooldownUntil) { filtStr += "CD "; blocked = true; }
   if(!IsSpreadOK()) { filtStr += "SPR "; blocked = true; }
   if(InpUseATRFilter && !IsATROK()) { filtStr += "ATR "; blocked = true; }
   if(!blocked) filtStr += "OK";
   STxt(PNL_PREFIX + "FILT", filtStr);
   SClr(PNL_PREFIX + "FILT", blocked ? InpBearClr : InpBullClr);

   string status;
   if(TimeCurrent() < g_cooldownUntil)
      status = "Status: COOLDOWN " + IntegerToString((int)((g_cooldownUntil - TimeCurrent()) / 3600)) + "h";
   else if(InpNoFriday && IsFriday())
      status = "Status: FRIDAY - NO TRADE";
   else if(InpNoMondayAM && IsMondayMorning())
      status = "Status: MON AM - GAP RISK";
   else if(InpNewsFilter && IsNewsTime())
      status = "Status: NEWS TIME - PAUSED";
   else if(!IsSpreadOK())
      status = "Status: SPREAD ӨНДӨР";
   else if(InpUseATRFilter && !IsATROK())
      status = "Status: VOLATILITY FILTER";
   else if(g_todayTrades >= InpMaxTradesDay)
      status = "Status: ӨДРИЙН LIMIT";
   else if(g_waitingForClose)
      status = "Status: TRADE OPEN";
   else if(g_tier.setup.valid)
      status = "Status: ★ ENTRY READY ★";
   else if(g_tier.m5Ready)
      status = "Status: M1 retest хүлээж...";
   else
      status = "Status: SCANNING...";
   STxt(PNL_PREFIX + "WAIT", status);
   color stClr = InpPanelText;
   if(TimeCurrent() < g_cooldownUntil) stClr = InpBearClr;
   else if(blocked) stClr = C'255,152,0';
   else if(g_waitingForClose) stClr = C'255,152,0';
   else if(g_tier.setup.valid) stClr = InpBullClr;
   else if(g_tier.m5Ready) stClr = InpEntryClr;
   else stClr = C'180,180,50';
   SClr(PNL_PREFIX + "WAIT", stClr);

   ChartRedraw(0);
}

//--- Panel helpers
void PBtn(string nm, int x, int y, int w, int h, string txt, color bg)
{
   if(ObjectFind(0,nm)>=0) ObjectDelete(0,nm);
   ObjectCreate(0,nm,OBJ_BUTTON,0,0,0);
   ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,x); ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,nm,OBJPROP_XSIZE,w); ObjectSetInteger(0,nm,OBJPROP_YSIZE,h);
   ObjectSetString(0,nm,OBJPROP_TEXT,txt); ObjectSetString(0,nm,OBJPROP_FONT,"Segoe UI");
   ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,8); ObjectSetInteger(0,nm,OBJPROP_COLOR,clrWhite);
   ObjectSetInteger(0,nm,OBJPROP_BGCOLOR,bg); ObjectSetInteger(0,nm,OBJPROP_BORDER_COLOR,C'50,50,65');
   ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false); ObjectSetInteger(0,nm,OBJPROP_STATE,false);
}

void PLbl(string nm, int x, int y, string txt, color c, int sz, bool b)
{
   if(ObjectFind(0,nm)>=0) ObjectDelete(0,nm);
   ObjectCreate(0,nm,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,x); ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,y);
   ObjectSetString(0,nm,OBJPROP_TEXT,txt); ObjectSetString(0,nm,OBJPROP_FONT,b?"Segoe UI Semibold":"Segoe UI");
   ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,sz); ObjectSetInteger(0,nm,OBJPROP_COLOR,c);
   ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER); ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
}

void PRect(string nm, int x, int y, int w, int h, color bg)
{
   if(ObjectFind(0,nm)>=0) ObjectDelete(0,nm);
   ObjectCreate(0,nm,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,x); ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,nm,OBJPROP_XSIZE,w); ObjectSetInteger(0,nm,OBJPROP_YSIZE,h);
   ObjectSetInteger(0,nm,OBJPROP_BGCOLOR,bg); ObjectSetInteger(0,nm,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,nm,OBJPROP_BORDER_COLOR,C'50,50,65');
   ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER); ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,nm,OBJPROP_BACK,false);
}

void STxt(string nm, string txt) { if(ObjectFind(0,nm)>=0) ObjectSetString(0,nm,OBJPROP_TEXT,txt); }
void SClr(string nm, color c)    { if(ObjectFind(0,nm)>=0) ObjectSetInteger(0,nm,OBJPROP_COLOR,c); }
//+------------------------------------------------------------------+