param (
    [string]$CommitMessage = "Синхронизация проекта"
)

Write-Host "Запуск синхронизации..." -ForegroundColor Cyan

# 1. Переключаемся на рабочую ветку
git checkout camera_class

# 2. Фиксируем локальные изменения (если они есть)
git add .
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m $CommitMessage
}

# 3. Подтягиваем свежие коммиты из origin перед пушем
Write-Host "Подтягивание обновлений из origin..." -ForegroundColor Yellow
git pull origin camera_class --rebase
if ($LASTEXITCODE -ne 0) {
    Write-Host "ОШИБКА: Конфликт при получении данных из origin. Разрешите конфликт вручную." -ForegroundColor Red
    exit 1
}

# 4. Отправляем изменения в рабочий origin
Write-Host "Отправка в AO-CCB-Deyton/Milandr (origin)..." -ForegroundColor Yellow
git push origin camera_class
if ($LASTEXITCODE -ne 0) {
    Write-Host "ОШИБКА: Не удалось отправить данные в origin." -ForegroundColor Red
    exit 1
}

# 5. Удаляем временную ветку только если она действительно существует
if (git branch --list temp_flat) {
    git branch -D temp_flat | Out-Null
}

# 6. Собираем чистый слепок для личной копии
git checkout --orphan temp_flat
git add .
git commit -m "Синхронизация личной копии проекта (Автоскрипт)"

# 7. Отправляем срез в личный репозиторий
Write-Host "Отправка в gloOryY/Milandr_my_copy (my_copy)..." -ForegroundColor Yellow
git push -f my_copy temp_flat:camera_class

# 8. Возвращаемся в camera_class и удаляем временную ветку
git checkout camera_class
if (git branch --list temp_flat) {
    git branch -D temp_flat | Out-Null
}
git branch --set-upstream-to=origin/camera_class camera_class

Write-Host "Синхронизация успешно завершена! Изменения в обоих репозиториях." -ForegroundColor Green