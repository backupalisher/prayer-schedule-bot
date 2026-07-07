#!/usr/bin/env bash
# Управление ботом расписания намазов
# Использование: ./run.sh {start|stop|restart|status|logs|setup}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/bot.pid"
LOG_FILE="$SCRIPT_DIR/bot.log"
VENV_DIR="$SCRIPT_DIR/.venv"
ENV_FILE="$SCRIPT_DIR/.env"
MAIN="$SCRIPT_DIR/main.py"
SERVICE_NAME="prayer-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Можно переопределить: PYTHON_BIN=python3.12 ./run.sh setup
PYTHON_BIN="${PYTHON_BIN:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

find_python() {
    if [[ -n "$PYTHON_BIN" ]]; then
        if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
            echo "$PYTHON_BIN"
            return 0
        fi
        log_error "PYTHON_BIN=$PYTHON_BIN не найден"
        return 1
    fi

    local candidate version major minor
    for candidate in python3.13 python3.12 python3.11 python3; do
        if ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi
        version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        major="${version%%.*}"
        minor="${version#*.}"
        if [[ "$major" -eq 3 && "$minor" -ge 11 && "$minor" -le 13 ]]; then
            echo "$candidate"
            return 0
        fi
    done

    log_error "Нужен Python 3.11–3.13. На системе только Python 3.14+, он пока не поддерживается зависимостями (pydantic, aiogram)."
    echo ""
    echo "Скрипт попробует установить Python 3.12 через uv автоматически."
    echo "Или вручную:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  rm -rf .venv && ./run.sh setup"
    return 1
}

ensure_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        log_error "Файл .env не найден. Запустите: ./run.sh setup"
        exit 1
    fi
}

resolve_paths() {
    PYTHON="$VENV_DIR/bin/python"
    if [[ -x "$PYTHON" ]]; then
        return 0
    fi
    SYSTEM_PYTHON="$(find_python)"
}

venv_python_version() {
    if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        echo "0.0"
        return
    fi
    "$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0"
}

venv_version_ok() {
    local version="$1"
    local major="${version%%.*}"
    local minor="${version#*.}"
    [[ "$major" -eq 3 && "$minor" -ge 11 && "$minor" -le 13 ]]
}

ensure_uv() {
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        log_info "Установка uv (менеджер Python для проекта)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
    command -v uv >/dev/null 2>&1
}

create_venv() {
    if ensure_uv; then
        log_info "Создание виртуального окружения через uv (Python 3.12)..."
        uv python install 3.12
        uv venv --python 3.12 "$VENV_DIR"
        return 0
    fi

    resolve_paths
    log_info "Создание виртуального окружения ($SYSTEM_PYTHON)..."
    "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
}

install_requirements() {
    local version
    version="$(venv_python_version)"
    log_info "Установка зависимостей (Python $version)..."

    if [[ -x "$VENV_DIR/bin/pip" ]]; then
        "$VENV_DIR/bin/pip" install -q --upgrade pip
        "$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
    elif ensure_uv; then
        uv pip install -r "$SCRIPT_DIR/requirements.txt" --python "$VENV_DIR/bin/python"
    else
        "$VENV_DIR/bin/python" -m ensurepip --upgrade
        "$VENV_DIR/bin/python" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
    fi
}

ensure_venv() {
    if [[ -d "$VENV_DIR" ]]; then
        local venv_version
        venv_version="$(venv_python_version)"
        if ! venv_version_ok "$venv_version"; then
            log_warn "Удаляю .venv (Python $venv_version не поддерживается, нужен 3.11–3.13)..."
            rm -rf "$VENV_DIR"
        fi
    fi

    if [[ ! -d "$VENV_DIR" ]]; then
        if ! create_venv; then
            log_error "Не удалось создать виртуальное окружение"
            exit 1
        fi
    fi

    resolve_paths
    if [[ ! -x "$PYTHON" ]]; then
        log_error "Python в venv не найден: $PYTHON"
        exit 1
    fi

    install_requirements
}

get_pid() {
    pgrep -f "[p]ython.*${MAIN}" 2>/dev/null | head -1 || true
}

is_systemd_active() {
    systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null
}

is_running() {
    local pid
    pid="$(get_pid)"
    [[ -n "$pid" ]]
}

cmd_setup() {
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$SCRIPT_DIR/.env.example" ]]; then
            cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
            log_info "Создан .env из .env.example — укажите BOT_TOKEN"
        else
            cat > "$ENV_FILE" <<'EOF'
USE_TELEGRAM=True
BOT_TOKEN=
MONITOR_ALERTS_ENABLED=False
DATABASE_URL=sqlite:///prayers.db
EOF
            log_info "Создан базовый .env — укажите BOT_TOKEN"
        fi
    else
        log_info ".env уже существует"
    fi

    ensure_venv
    log_info "Окружение готово. Отредактируйте .env и запустите: ./run.sh start"
}

cmd_start() {
    ensure_env
    ensure_venv
    resolve_paths

    if is_running; then
        log_warn "Бот уже запущен (PID: $(get_pid))"
        exit 0
    fi

    # Проверка токена
    # shellcheck disable=SC1090
    source <(grep -E '^[A-Z_]+=' "$ENV_FILE" | sed 's/^/export /')
    if [[ "${USE_TELEGRAM:-False}" == "True" && -z "${BOT_TOKEN:-}" ]]; then
        log_error "BOT_TOKEN не задан в .env"
        exit 1
    fi

    log_info "Запуск бота..."
    nohup "$PYTHON" "$MAIN" >> "$LOG_FILE" 2>&1 &

    sleep 3
    local pid
    pid="$(get_pid)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        log_info "Бот запущен (PID: $pid)"
        log_info "Логи: $LOG_FILE"
    else
        log_error "Бот не запустился. Последние строки лога:"
        tail -20 "$LOG_FILE" 2>/dev/null || true
        exit 1
    fi
}

cmd_stop() {
    if is_systemd_active; then
        log_info "Остановка systemd-сервиса $SERVICE_NAME..."
        sudo systemctl stop "$SERVICE_NAME"
        log_info "Сервис остановлен"
        return 0
    fi

    if ! is_running; then
        log_warn "Бот не запущен"
        rm -f "$PID_FILE"
        exit 0
    fi

    local pid
    pid="$(get_pid)"
    log_info "Остановка бота (PID: $pid)..."

    kill -TERM "$pid" 2>/dev/null || true

    local i
    for i in $(seq 1 10); do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            log_info "Бот остановлен"
            return 0
        fi
        sleep 1
    done

    log_warn "Принудительное завершение..."
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    log_info "Бот остановлен (SIGKILL)"
}

cmd_restart() {
    cmd_stop || true
    sleep 1
    cmd_start
}

cmd_status() {
    if is_systemd_active; then
        log_info "Systemd-сервис $SERVICE_NAME активен"
        systemctl status "$SERVICE_NAME" --no-pager -l | head -15
        return 0
    fi

    if is_running; then
        local pid
        pid="$(get_pid)"
        log_info "Бот работает (PID: $pid)"
        ps -p "$pid" -o pid,etime,cmd --no-headers 2>/dev/null || true
        log_warn "Рекомендуется: ./run.sh install-service && ./run.sh enable-service"
    else
        log_warn "Бот не запущен"
        exit 1
    fi
}

cmd_install_service() {
    ensure_venv
    resolve_paths

    if [[ ! -x "$PYTHON" ]]; then
        log_error "Python не найден: $PYTHON. Сначала выполните ./run.sh setup"
        exit 1
    fi

    local template="$SCRIPT_DIR/deploy/prayer-bot.service"
    if [[ ! -f "$template" ]]; then
        log_error "Шаблон не найден: $template"
        exit 1
    fi

    sed \
        -e "s|__WORKDIR__|$SCRIPT_DIR|g" \
        -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__MAIN__|$MAIN|g" \
        -e "s|__LOGFILE__|$LOG_FILE|g" \
        "$template" | sudo tee "$SERVICE_FILE" >/dev/null

    sudo systemctl daemon-reload
    log_info "Сервис установлен: $SERVICE_FILE"
    log_info "Запуск: sudo ./run.sh enable-service"
}

cmd_enable_service() {
    if [[ ! -f "$SERVICE_FILE" ]]; then
        log_error "Сервис не установлен. Выполните: ./run.sh install-service"
        exit 1
    fi

    if is_running && ! is_systemd_active; then
        log_warn "Останавливаю процесс, запущенный через nohup..."
        cmd_stop || true
        sleep 2
    fi

    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2

    if is_systemd_active; then
        log_info "Сервис $SERVICE_NAME запущен с автоперезапуском"
        systemctl status "$SERVICE_NAME" --no-pager -l | head -10
    else
        log_error "Не удалось запустить сервис. Лог:"
        journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
        exit 1
    fi
}

cmd_disable_service() {
    if [[ -f "$SERVICE_FILE" ]]; then
        sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
        log_info "Systemd-сервис остановлен и отключён"
    else
        log_warn "Systemd-сервис не установлен"
    fi
}

cmd_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        log_warn "Лог-файл не найден: $LOG_FILE"
        exit 1
    fi
    tail -f "$LOG_FILE"
}

usage() {
    echo "Использование: $0 {start|stop|restart|status|logs|setup|install-service|enable-service|disable-service}"
    echo ""
    echo "  setup            — создать .env и установить зависимости"
    echo "  start            — запустить бота в фоне (nohup, без автоперезапуска)"
    echo "  stop             — остановить бота"
    echo "  restart          — перезапустить бота"
    echo "  status           — проверить статус"
    echo "  logs             — следить за логами (tail -f)"
    echo ""
    echo "  install-service  — установить systemd-сервис (рекомендуется для сервера)"
    echo "  enable-service   — включить автозапуск и автоперезапуск через systemd"
    echo "  disable-service  — остановить и отключить systemd-сервис"
}

case "${1:-}" in
    start)            cmd_start ;;
    stop)             cmd_stop ;;
    restart)          cmd_restart ;;
    status)           cmd_status ;;
    logs)             cmd_logs ;;
    setup)            cmd_setup ;;
    install-service)  cmd_install_service ;;
    enable-service)   cmd_enable_service ;;
    disable-service)  cmd_disable_service ;;
    *)
        usage
        exit 1
        ;;
esac
