# MQL5 Expert Advisor

`bridge_ea.mq5` нь Python brain-тэй ZeroMQ-р холбогдох "thin" EA.

## Build

1. MT5 терминал → File → Open Data Folder → `MQL5/Experts/` дотор хуулна.
2. MetaEditor → F7 (compile).
3. `libzmq.dll` (x64) -ийг `MQL5/Libraries/` дотор тавина. Pre-built бүтээгдэхүүн:
   <https://github.com/dingmaotu/mql-zmq>
4. Tools → Options → Expert Advisors → **Allow DLL imports** асаах.

## Анхаар

- `AllowExecution = false` гэдэг **default**. true болгохын өмнө paper acct
  дээр 4 долоо хоног соак хийсэн байх ёстой.
- VPS дээр deploy хийхдээ broker-ийн VPS-д DLL imports блоклогдсон эсэхийг
  шалга. Block байвал custom DLL биш TCP forwarder сонгох ёстой.

## Wire format (одоогийн хувилбар)

MT5 ↔ Python хооронд **pipe-delimited string** + HMAC-SHA256 hex prefix
ашигладаг (msgpack-ийг MQL5-д бичих хэцүү учир). Format:

```
<hmac_hex>|<body>
body = "<type>|<k1>=<v1>|<k2>=<v2>|..."
```

Жишээ: `tick|symbol=EURUSD|bid=1.10412|ask=1.10421|ts_ms=1735776000123|volume=0`.

Python тал нь `bridge/transport.py`-ийн msgpack frame-ийн оронд энэ format-ыг
parse хийх ёстой. Хожим msgpack DLL (https://github.com/msgpack/msgpack-c)
импортлох замаар сольж болно.

## Үлдсэн TODO

1. **Python тал MQL5-ийн pipe format-ыг parse хийх adapter** —
   `bridge/transport.py`-д `decode_pipe(frame)` нэмэх (хагас үлдсэн).
2. **Order execution acknowledgement back-channel** — fill price-ийг
   journal руу буцаах ёстой (одоо RPC reply-аар буцаагдаж байна, гэхдээ
   Python тал дахь RPC client одоогоор бичигдээгүй).
3. **Live test** — VPS дээр paper acct-аар 4 долоо хоног.
