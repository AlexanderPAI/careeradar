# Проверка TLS для GigaChat

GigaChat использует цепочку сертификатов НУЦ Минцифры. Стандартное хранилище CA
в Debian и Python может не содержать эту цепочку, из-за чего соединение
завершается ошибкой `CERTIFICATE_VERIFY_FAILED`. Отключать проверку TLS для
исправления этой ошибки нельзя.

В проекте зафиксированы ожидаемые отпечатки официальных сертификатов:

- `Russian Trusted Root CA`, SHA-256
  `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`;
- `Russian Trusted Sub CA`, SHA-256
  `BB:BD:E2:10:3E:79:0B:99:9E:C6:2B:D0:3C:F6:25:A5:A2:E7:C3:16:E1:0A:FE:6A:49:0E:ED:EA:D8:B3:FD:9B`.

Сами сертификаты не хранятся в Git: каталог `backend/certs/` находится в
`.gitignore` и `.dockerignore`. Dockerfile не скачивает и не содержит
сертификаты. Перед запуском файлы размещаются оператором в `backend/certs/`, а
Compose подключает каталог в контейнер в режиме read-only по пути
`/run/careeradar/certs`.

REST-клиент загружает сертификаты напрямую в проверяющий `SSLContext` по путям,
заданным переменными:

```env
GIGACHAT_VERIFY_SSL_CERTS=true
GIGACHAT_ROOT_CA_FILE=backend/certs/russian_trusted_root_ca.pem
GIGACHAT_SUB_CA_FILE=backend/certs/russian_trusted_sub_ca.pem
```

При `APP_ENV=production` значение `GIGACHAT_VERIFY_SSL_CERTS=false` приводит к
ошибке конфигурации до запуска приложения. В development его можно использовать
только для кратковременной диагностики, но штатная конфигурация также использует
`true`.

При плановой замене сертификатов нужно скачать новые файлы с официального
портала, проверить subject, issuer и SHA-256 fingerprint и заменить локальные
файлы. Пересборка образа не требуется; достаточно перезапустить backend.
