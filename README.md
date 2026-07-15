Основной web origin: `https://docs.e-qoldau.asia`

Основной API origin: `https://api.e-qoldau.asia`

Локальный запуск допустим только как dev-режим. Прод-контур должен ориентироваться на `.env.production`.

Проверка health:
```powershell
curl.exe "https://api.e-qoldau.asia/api/health"
```

Справочник форм:
```powershell
curl.exe "https://api.e-qoldau.asia/api/forms"
```

Режимы загрузки:
```powershell
curl.exe "https://api.e-qoldau.asia/api/upload-modes"
```

Отчет по форме `2-43`:
```powershell
curl.exe "https://api.e-qoldau.asia/api/reports/2-43?kbk=101111&date_from=2025-03-01&date_to=2025-03-31"
```

Последний документ по любой форме:
```powershell
curl.exe "https://api.e-qoldau.asia/api/reports/5-52/latest"
```

Загрузка PDF через консоль:
```powershell
curl.exe -X POST "https://api.e-qoldau.asia/api/uploads" `
  -F "form_type=form_2_43" `
  -F "upload_mode=pdf_text" `
  -F "files=@D:\path\to\2-43.pdf;type=application/pdf"
```

Проверить реестр:
```powershell
curl.exe "https://api.e-qoldau.asia/api/documents"
```

Проверка опорных PDF по формам:
```powershell
.\run_verify_forms.bat
```

Автозапуск на Windows Server без входа в систему:
```powershell
powershell.exe -ExecutionPolicy Bypass -File .\ops\windows-server\install-background-tasks.ps1
```

Проверить состояние фоновых задач:
```powershell
powershell.exe -ExecutionPolicy Bypass -File .\ops\windows-server\status.ps1
```

Удалить автозапуск:
```powershell
powershell.exe -ExecutionPolicy Bypass -File .\ops\windows-server\remove-background-tasks.ps1
```

Логи фонового запуска:

- `backend/logs/backend.out.log`
- `backend/logs/backend.err.log`
- `backend/logs/workers.out.log`
- `backend/logs/workers.err.log`
- `backend/logs/frontend.out.log`
- `backend/logs/frontend.err.log`
- `runtime/windows-server/watchdog.log`

Отчеты верификации сохраняются в:

- `docs/verification/form-samples-report.json`
- `docs/verification/form-samples-report.md`
