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

## Дараагийн алхам

`OnTick`, `ExecuteOrder`, `FlattenAll` доторх `// TODO`-уудыг бөглө.
HMAC + msgpack нь Python тал дээртэй адил байх ёстой —
`bridge/transport.py`-аас format-аа авна.
