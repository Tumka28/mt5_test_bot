# SMC Pure EA v3.4-SLHUNT — XAUUSD trading EA

`SMC_Pure_EA.mq5` нь Smart Money Concepts (SMC) бие даасан, бүрэн EA. Манай
`bridge_ea.mq5`-аас (ZAW research bridge) тусдаа — **өөрийн trade execution
+ risk management-тэй**.

## Архитектурт яаж зохицох вэ

```
┌─────────────────────────────────────────────────────────────────┐
│  MT5 Demo Account                                               │
│                                                                 │
│  ┌───────────────────────┐        ┌──────────────────────────┐ │
│  │ XAUUSD chart           │        │ EURUSD chart             │ │
│  │ ─ SMC_Pure_EA          │        │ ─ bridge_ea (research)   │ │
│  │ ─ Magic 777032         │        │ ─ Magic 0 (default)      │ │
│  │ ─ Бие даан trade хийнэ │        │ ─ tick + account → brain │ │
│  └───────────────────────┘        └──────────────────────────┘ │
│            │                                  │                  │
│            ▼                                  ▼                  │
│   ┌──────────────┐               ┌──────────────────────────┐  │
│   │ XAUUSD trades│               │ Python brain (research)  │  │
│   │ (SMC own)    │               │ (paper / shadow / live)  │  │
│   └──────────────┘               └──────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Хоёр EA нь **тус тусын Magic Number**-тэй — нэг нь нөгөөгийн trade-д
хөнддөггүй. Тус тус өөрсдийн symbol-д л хязгаарлагдана.

## Setup

### 1. Compile болсон эсэх (auto-completed)

`MQL5/Experts/SMC_Pure_EA.ex5` (121 KB) бэлэн.

### 2. MT5 терминалд:
- `Tools → Options → Expert Advisors`:
  - ☑ Allow algorithmic trading
  - ☑ Allow WebRequest URL = `http://127.0.0.1:5555` (зөвхөн bridge_ea-д хэрэгтэй)
- Toolbar дээр **"Algo Trading"** товч асаах

### 3. Demo акаунттай чарт:
- **XAUUSD chart нээ** (M1 эсвэл M5, аль ч timeframe ажиллана — EA дотроос HTF/MTF/LTF өөрөө сонгоно)
- Navigator → Expert Advisors → `SMC_Pure_EA` chart руу drag&drop

### 4. Inputs dialog:

⚠️ **Зөвлөж буй default**-ууд (ULTRA-SAFE):

| Параметр | Утга | Тайлбар |
|---|---|---|
| `InpRiskPct` | **0.3** | Trade-д 0.3% эрсдэл |
| `InpMaxLotSize` | **0.03** | Хамгийн их lot |
| `InpMaxDailyLoss` | **1.0** | Өдрийн max алдагдал 1% |
| `InpMaxTradesDay` | **2** | Өдөрт max 2 trade |
| `InpMaxConsecLoss` | **2** | 2 алдагдал — 24h cooldown |
| `InpCooldownHours` | **24** | Cooldown |
| `InpNoFriday` | **true** | Баасан no trade |
| `InpNoMondayAM` | **true** | Даваа өглөө no trade (gap risk) |
| `InpSessionStart` | **8** | London open (GMT) |
| `InpSessionEnd` | **20** | NY close (GMT) |
| `InpMaxSpreadPts` | **50** | Spread > 50 points → skip |
| `InpNewsFilter` | **true** | Their news filter |
| `InpBlockNFP/FOMC/CPI` | **true** | Хүчтэй мэдээний өмнө 60м blackout |

**Бүх default-ыг үл хөнд** — зориудаар conservative бүтсэн. Risk-ийг сулруулсан тохиолдолд EA-ийн safety logic ажиллахгүй болно.

- **OK**

### 5. Үр дүн харах

Chart-ийн баруун дээр SMC EA panel гарна (entry/SL/TP plotting). Toolbox → Experts tab-д journal:
```
SMC Pure EA v3.4 init  symbol=XAUUSD risk=0.3% max_lot=0.03
```

Trade гарвал:
```
ENTRY BUY XAUUSD lots=0.03 sl=2018.50 tp=2024.50 rr=1.5
```

## Хоёр EA-г нэг demo-д ажиллуулахдаа

| EA | Symbol | Magic | Үүрэг |
|---|---|---|---|
| `SMC_Pure_EA` | XAUUSD | 777032 | Бие даан trade |
| `bridge_ea` | EURUSD | 0 (default) | Research / data collection |

**Анхаар:** хоёр EA нь **ижил акаунтын equity** дээр огт тусгаар. SMC -1% хийвэл bridge_ea-ийн сэтгэл хөөрөл тэрнээс хамаарна. Нэг ийм risk-cluster effect-ыг нэг demo-д хүлээнэ үү.

## Ariljaa-руу шилжих 4 алхам

1. **Demo акаунтаар 4 долоо хоног SMC EA-г үргэлжлүүлэн ажиллуул.** Trade history-г нь долоо хоногт нэг шалгана.
2. Win rate, average loss, max drawdown тогтвортой эсэхийг ажигла.
3. Хэрэв **тогтвортой ашигтай** (positive expectancy) бол real money акаунт руу шилжүүл — гэхдээ:
   - `InpRiskPct = 0.1` (1/3 болгож багасга)
   - `InpMaxLotSize = 0.01`
   - 2 долоо хоног нийгэмийн size-аар
4. Зөвхөн дээрх 2 долоо хоног эерэг бол л full size-руу шилжүүл.

## ⚠️ ВАНРНИНГ

- **100% алдагдалгүй EA байдаггүй.** SMC ч мөн адил.
- EA-ийн description дотор шууд бичсэн: "Энэ хувилбар зөвхөн алдагдлын магадлалыг **багасгана**."
- 24h cooldown ажилласан тохиолдолд **тэр өдрийг алгасах** — restart-аар disarm бүү хий.
- News blackout-ыг **үл хөнд** — high-impact news үед Gold spread 5x хүртэл өргөдөг, slippage сонгох боломжгүй.
