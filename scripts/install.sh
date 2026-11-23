#!/bin/bash
# One-command, per-user Apple Silicon installer. Compatible with macOS Bash 3.2.
set -euo pipefail
# >>> caravan strings (generated from locales/*.json; edit those, then run: python3 tools/caravan_i18n.py --sync-shell) >>>
_caravan_ui_lang() {
  _caravan_norm_lang() {
    c=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr '_' '-' | cut -d. -f1)
    case "$c" in
      es|es-*) printf '%s' es ;;
      en|en-*) printf '%s' en ;;
      ja|ja-*) printf '%s' ja ;;
      ru|ru-*) printf '%s' ru ;;
      zh-hant|zh-hant-*) printf '%s' zh-Hant ;;
      zh-hans|zh-hans-*) printf '%s' zh-Hans ;;
      zh-tw|zh-tw-*|zh-hk|zh-hk-*|zh-mo|zh-mo-*) printf '%s' zh-Hant ;;
      zh-cn|zh-cn-*|zh-sg|zh-sg-*|zh) printf '%s' zh-Hans ;;
      *) printf '%s' "$c" ;;
    esac
  }
  _caravan_have_lang() {
    case "$1" in
      en|es|ja|ru|zh-Hans) return 0 ;;
      *) return 1 ;;
    esac
  }
  if [ -n "${CARAVAN_LANG:-}" ]; then
    n=$(_caravan_norm_lang "$CARAVAN_LANG")
    if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
  fi
  if [ -f "${HOME}/.caravan/prefs" ]; then
    p=$(sed -n 's/.*"language"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${HOME}/.caravan/prefs" | head -n 1)
    if [ -n "$p" ]; then
      n=$(_caravan_norm_lang "$p")
      if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
    fi
  fi
  if command -v defaults >/dev/null 2>&1; then
    for tag in $(defaults read -g AppleLanguages 2>/dev/null | tr -d '"(),' ); do
      [ -n "$tag" ] || continue
      n=$(_caravan_norm_lang "$tag")
      if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
    done
  fi
  if [ -n "${LC_ALL:-}" ] && [ "${LC_ALL}" != "C" ] && [ "${LC_ALL}" != "POSIX" ]; then
    n=$(_caravan_norm_lang "$LC_ALL")
    if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
  fi
  if [ -n "${LANG:-}" ] && [ "${LANG}" != "C" ] && [ "${LANG}" != "POSIX" ]; then
    n=$(_caravan_norm_lang "$LANG")
    if _caravan_have_lang "$n"; then printf '%s' "$n"; return; fi
  fi
  printf '%s' en
}
CARAVAN_UI_LANG=$(_caravan_ui_lang)
S_unknown_option_arg_use_help() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Opción desconocida: ${1}. Usa --help." ;; ja) printf '%s' "不明なオプション: ${1}。--help を使用してください。" ;; ru) printf '%s' "Неизвестный параметр: ${1}. Используй --help." ;; zh-Hans) printf '%s' "未知选项：${1}。请使用 --help。" ;; *) printf '%s' "Unknown option: ${1}. Use --help." ;; esac; }
S_setup_stopped_models_and_existing_settings() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se detuvo la instalación. No se eliminaron los modelos ni los ajustes existentes. Corrige el error de arriba y vuelve a ejecutar el mismo comando." ;; ja) printf '%s' "セットアップが停止しました。モデルと既存の設定は削除されませんでした。上記のエラーを修正した後、同じコマンドを再度実行してください。" ;; ru) printf '%s' "Настройка остановлена. Модели и существующие настройки не были удалены. Исправьте ошибку выше, затем запусти ту же команду снова." ;; zh-Hans) printf '%s' "设置已停止。模型和现有设置未被移除。请修复上述错误，然后重新运行相同命令。" ;; *) printf '%s' "Setup stopped. Models and existing settings were not removed. Fix the error above, then rerun the same command." ;; esac; }
S_arg_needs_a_value_2() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "${1} necesita un valor." ;; ja) printf '%s' "${1} に値が必要です。" ;; ru) printf '%s' "${1} требует значения." ;; zh-Hans) printf '%s' "${1} 需要一个值。" ;; *) printf '%s' "${1} needs a value." ;; esac; }
S_choose_a_port_number_from_1() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Elige un número de puerto del 1 al 65535." ;; ja) printf '%s' "1 から 65535 の範囲からポート番号を選択してください。" ;; ru) printf '%s' "Выбери номер порта от 1 до 65535." ;; zh-Hans) printf '%s' "选择 1 到 65535 之间的端口号。" ;; *) printf '%s' "Choose a port number from 1 to 65535." ;; esac; }
S_choose_role_lead_or_role_worker() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Elige --role lead o --role worker." ;; ja) printf '%s' "--role lead または --role worker を選択してください。" ;; ru) printf '%s' "Выбери --role lead или --role worker." ;; zh-Hans) printf '%s' "选择 --role lead 或 --role worker。" ;; *) printf '%s' "Choose --role lead or --role worker." ;; esac; }
S_install_the_web_ui_as_lead() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Instala primero la página web como lead; usa caravan_service.py para un plan opcional de arranque automático del modelo." ;; ja) printf '%s' "まず lead として Web UI をインストールしてください。オプションのモデル自動起動計画には caravan_service.py を使用してください。" ;; ru) printf '%s' "Сначала установи веб-интерфейс как lead; используй caravan_service.py для опционального плана автозапуска моделей." ;; zh-Hans) printf '%s' "先以 lead 身份安装 Web UI；如需可选的模型自动启动计划，请使用 caravan_service.py。" ;; *) printf '%s' "Install the web UI as lead first; use caravan_service.py for an optional model auto-start plan." ;; esac; }
S_worker_stage_options_need_an_installed() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Las opciones de etapa de worker necesitan una carpeta --model instalada. No se configuró ningún worker." ;; ja) printf '%s' "Worker ステージオプションには、インストールされた --model フォルダが必要です。Worker は設定されていません。" ;; ru) printf '%s' "Опции этапа worker требуют установленной папки --model. Worker не был настроен." ;; zh-Hans) printf '%s' "Worker 阶段选项需要一个已安装的 --model 文件夹。未配置任何 Worker。" ;; *) printf '%s' "Worker stage options need an installed --model folder. No worker was configured." ;; esac; }
S_repo_must_be_an_absolute_path() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "--repo debe ser una ruta absoluta (usa \"\$HOME/...\", no un ~ literal)." ;; ja) printf '%s' "--repo は絶対パスである必要があります（\"\$HOME/...\"を使用し、文字列の ~ を使用しないでください）。" ;; ru) printf '%s' "--repo должен быть абсолютным путём (используй \"\$HOME/...\", а не буквальное ~)." ;; zh-Hans) printf '%s' "--repo 必须是绝对路径（使用 \"\$HOME/...\"，而非字面量的 ~）。" ;; *) printf '%s' "--repo must be an absolute path (use \"\$HOME/...\", not a literal ~)." ;; esac; }
S_ref_must_name_a_git_branch() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "--ref debe ser una rama o etiqueta de Git." ;; ja) printf '%s' "--ref は Git ブランチまたはタグの名前を指定してください。" ;; ru) printf '%s' "--ref должен указывать на ветку или тег Git." ;; zh-Hans) printf '%s' "--ref 必须指定一个 Git 分支或标签名称。" ;; *) printf '%s' "--ref must name a Git branch or tag." ;; esac; }
S_choose_a_dedicated_caravan_folder_not() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Elige una carpeta dedicada de Caravan, no / ni tu carpeta de inicio." ;; ja) printf '%s' "専用の Caravan フォルダを選択してください。/ またはホームフォルダを使用しないでください。" ;; ru) printf '%s' "Выбери отдельную папку Caravan, а не / или твою домашнюю папку." ;; zh-Hans) printf '%s' "请选择专用的 Caravan 文件夹，不要选择 / 或你的主目录。" ;; *) printf '%s' "Choose a dedicated Caravan folder, not / or your home folder." ;; esac; }
S_preview_only_no_directories_downloads_packag() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "SOLO VISTA PREVIA: no se cambiarán carpetas, descargas, paquetes, configuración ni tareas de launchd." ;; ja) printf '%s' "プレビューのみ：ディレクトリ、ダウンロード、パッケージ、設定、または launchd ジョブに変更はありません。" ;; ru) printf '%s' "ТОЛЬКО ПРЕДПРОСМОТР: директории, загрузки, пакеты, конфиги или задания launchd не будут изменены." ;; zh-Hans) printf '%s' "预览模式：不会更改任何目录、下载内容、包、配置或 launchd 任务。" ;; *) printf '%s' "PREVIEW ONLY: no directories, downloads, packages, config or launchd jobs will change." ;; esac; }
S_this_installer_needs_macos_nothing_was() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Este instalador necesita macOS. No se instaló nada." ;; ja) printf '%s' "このインストーラーは macOS が必要です。何もインストールされませんでした。" ;; ru) printf '%s' "Этот установщик требует macOS. Ничего не было установлено." ;; zh-Hans) printf '%s' "此安装程序需要 macOS。未安装任何内容。" ;; *) printf '%s' "This installer needs macOS. Nothing was installed." ;; esac; }
S_use_an_apple_silicon_mac_and() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Usa un Mac con Apple Silicon y una Terminal nativa (no Rosetta). No se instaló nada." ;; ja) printf '%s' "Apple Silicon Mac とネイティブの Terminal（Rosetta は使用しないでください）を使用してください。何もインストールされませんでした。" ;; ru) printf '%s' "Используй Mac с Apple Silicon и нативный Terminal (не Rosetta). Ничего не было установлено." ;; zh-Hans) printf '%s' "请使用 Apple Silicon Mac 和原生 Terminal（不要使用 Rosetta）。未安装任何内容。" ;; *) printf '%s' "Use an Apple Silicon Mac and a native Terminal (not Rosetta). Nothing was installed." ;; esac; }
S_macos_14_or_newer_is_required() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se necesita macOS 14 o posterior (se encontró ${1})." ;; ja) printf '%s' "macOS 14 以降が必要です (検出: ${1})." ;; ru) printf '%s' "Требуется macOS 14 или новее (найдено ${1})." ;; zh-Hans) printf '%s' "需要 macOS 14 或更高版本（检测到 ${1}）。" ;; *) printf '%s' "macOS 14 or newer is required (found ${1})." ;; esac; }
S_run_as_your_normal_macos_user() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Ejecútalo como tu usuario normal de macOS, no con sudo/root." ;; ja) printf '%s' "通常の macOS ユーザーとして実行してください、sudo/root は使用しないでください。" ;; ru) printf '%s' "Запускай как своего обычного пользователя macOS, а не sudo/root." ;; zh-Hans) printf '%s' "请以你正常的 macOS 用户身份运行，不要使用 sudo/root。" ;; *) printf '%s' "Run as your normal macOS user, not sudo/root." ;; esac; }
S_use_the_no_prerequisites_mac_bootstrap() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Usa el instalador de Mac sin requisitos previos en INSTALL.md, o pasa --python /ruta/absoluta/python3 (3.10+)." ;; ja) printf '%s' "INSTALL.md の no-prerequisites Mac bootstrap を使用するか、--python /absolute/path/python3 (3.10 以上) を指定してください。" ;; ru) printf '%s' "Используй Mac bootstrap без предварительных условий в INSTALL.md или передай --python /absolute/path/python3 (3.10+)." ;; zh-Hans) printf '%s' "请使用 INSTALL.md 中的无依赖 Mac 引导程序，或传递 --python /absolute/path/python3（需 3.10+）。" ;; *) printf '%s' "Use the no-prerequisites Mac bootstrap in INSTALL.md, or pass --python /absolute/path/python3 (3.10+)." ;; esac; }
S_python_3_10_or_newer_is() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se necesita Python 3.10 o posterior." ;; ja) printf '%s' "Python 3.10 以降が必要です。" ;; ru) printf '%s' "Требуется Python 3.10 или новее." ;; zh-Hans) printf '%s' "需要 Python 3.10 或更高版本。" ;; *) printf '%s' "Python 3.10 or newer is required." ;; esac; }
S_this_python_is_running_under_rosetta() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Este Python está corriendo bajo Rosetta. Elige un Python nativo arm64." ;; ja) printf '%s' "この Python は Rosetta で実行されています。ネイティブの arm64 Python を選択してください。" ;; ru) printf '%s' "Этот Python работает под Rosetta. Выбери нативный arm64 Python." ;; zh-Hans) printf '%s' "此 Python 正在 Rosetta 下运行。请选择原生 arm64 的 Python。" ;; *) printf '%s' "This Python is running under Rosetta. Choose a native arm64 Python." ;; esac; }
S_free_at_least_8_gb_before() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Libera al menos 8 GB antes de instalar; los modelos necesitan más." ;; ja) printf '%s' "インストールする前に少なくとも 8 GB の空き容量を確保してください; モデルにはさらに多くの容量が必要です。" ;; ru) printf '%s' "Освободи хотя бы 8 ГБ перед установкой; моделям нужно больше." ;; zh-Hans) printf '%s' "安装前请至少释放 8 GB 空间；模型需要更多。" ;; *) printf '%s' "Free at least 8 GB before installing; models need more." ;; esac; }
S_python_python() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Python: ${1}" ;; ja) printf '%s' "Python: ${1}" ;; ru) printf '%s' "Python: ${1}" ;; zh-Hans) printf '%s' "Python: ${1}" ;; *) printf '%s' "Python: ${1}" ;; esac; }
S_source_folder_repo_ref() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Carpeta del código: ${1} (${2})" ;; ja) printf '%s' "ソースフォルダ: ${1} (${2})" ;; ru) printf '%s' "Папка исходного кода: ${1} (${2})" ;; zh-Hans) printf '%s' "源文件夹：${1} (${2})" ;; *) printf '%s' "Source folder: ${1} (${2})" ;; esac; }
S_that_checkout_has_a_different_origin() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Esa copia tiene un origen distinto. Reutilízala a mano o elige una carpeta nueva." ;; ja) printf '%s' "そのチェックアウトのオリジンが異なります。手動で再利用するか、新しいフォルダを選択してください。" ;; ru) printf '%s' "Этот checkout имеет другой origin. Используй его вручную или выбери новую папку." ;; zh-Hans) printf '%s' "该检出点的来源不同。请手动复用或选择新文件夹。" ;; *) printf '%s' "That checkout has a different origin. Reuse it manually or choose a new folder." ;; esac; }
S_your_checkout_has_local_changes_keep() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Tu copia tiene cambios locales. Consérvalos; haz un commit o elige otra carpeta antes de instalar." ;; ja) printf '%s' "チェックアウトにローカルの変更があります。それらを保持してください; インストールする前にコミットするか、別のフォルダを選択してください。" ;; ru) printf '%s' "В твоем checkout есть локальные изменения. Оставь их; сделай коммит или выбери другую папку перед установкой." ;; zh-Hans) printf '%s' "你的检出点包含本地更改。请保留这些更改；安装前请提交或选择其他文件夹。" ;; *) printf '%s' "Your checkout has local changes. Keep them; commit or choose a different folder before installing." ;; esac; }
S_this_checkout_follows_the_old_branch() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Esta copia sigue el nombre de rama anterior ${1}; recibe las mismas versiones que main." ;; ja) printf '%s' "このチェックアウトは古いブランチ名 ${1} を追っています; main と同じリリースを取得します。" ;; ru) printf '%s' "Этот checkout следует старой ветке ${1}; он получает те же релизы, что и main." ;; zh-Hans) printf '%s' "此检出点遵循旧分支名称 ${1}；它将获得与 main 相同的发布版本。" ;; *) printf '%s' "This checkout follows the old branch name ${1}; it gets the same releases as main." ;; esac; }
S_checkout_is_current_not_ref_no() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "La copia está en ${1}, no en ${2}. No se cambió ninguna rama." ;; ja) printf '%s' "チェックアウトは ${1} で、${2} ではありません。ブランチは変更されていません。" ;; ru) printf '%s' "Checkout — это ${1}, а не ${2}. Ветку не меняли." ;; zh-Hans) printf '%s' "检出点是 ${1}，而非 ${2}。未更改任何分支。" ;; *) printf '%s' "Checkout is ${1}, not ${2}. No branch was changed." ;; esac; }
S_a_release_tag_is_immutable_choose() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Una etiqueta de versión no se modifica; elige una carpeta de instalación nueva para cambiar de versión." ;; ja) printf '%s' "リリースタグは不変です; リリースを変更するには新しいインストールフォルダを選択してください。" ;; ru) printf '%s' "Release-тег неизменяем; выбери новую папку установки, чтобы сменить релизы." ;; zh-Hans) printf '%s' "发布标签不可变；请选择新的安装文件夹以更改发布版本。" ;; *) printf '%s' "A release tag is immutable; choose a new install folder to change releases." ;; esac; }
S_matching_clean_checkout_found_leaving_its() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se encontró una copia limpia coincidente; su código se deja igual. Usa --update para un fast-forward limpio." ;; ja) printf '%s' "一致するクリーンなチェックアウトが見つかりました; コードは変更せずに残します。クリーンなファストフォワードプルには --update を使用してください。" ;; ru) printf '%s' "Найдено совпадающее чистое checkout; код оставляют без изменений. Используй --update для чистого fast-forward pull." ;; zh-Hans) printf '%s' "已找到匹配的干净检出点，其代码保持不变。请使用 --update 进行干净的快进拉取。" ;; *) printf '%s' "Matching clean checkout found; leaving its code unchanged. Use --update for a clean fast-forward pull." ;; esac; }
S_using_existing_extracted_source_no_git() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se usa el código extraído existente; no hay operaciones de Git." ;; ja) printf '%s' "既存の抽出されたソースを使用しています; Git 操作は行いません。" ;; ru) printf '%s' "Используется существующий извлеченный исходный код; операции Git не выполняются." ;; zh-Hans) printf '%s' "使用现有的解压源；无需执行 Git 操作。" ;; *) printf '%s' "Using existing extracted source; no Git operations." ;; esac; }
S_that_folder_already_exists_and_is() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Esa carpeta ya existe y no es una copia reconocida. Usa --use-existing para una versión extraída, o elige una ruta vacía." ;; ja) printf '%s' "そのフォルダは既に存在し、認識されたチェックアウトではありません。抽出されたリリースには --use-existing を使用するか、空のパスを選択してください。" ;; ru) printf '%s' "Эта папка уже существует и не является признанным checkout. Используй --use-existing для извлеченного релиза или выбери пустой путь." ;; zh-Hans) printf '%s' "该文件夹已存在且不是受支持的检出点。请使用 --use-existing 使用解压后的发布版本，或选择空路径。" ;; *) printf '%s' "That folder already exists and is not a recognized checkout. Use --use-existing for an extracted release, or choose an empty path." ;; esac; }
S_use_existing_needs_an_existing_caravan() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "--use-existing necesita una carpeta de código de Caravan que ya exista." ;; ja) printf '%s' "--use-existing は既存の Caravan ソースフォルダが必要です。" ;; ru) printf '%s' "--use-existing требует существующей папки исходного кода Caravan." ;; zh-Hans) printf '%s' "--use-existing 需要一个现有的 Caravan 源文件夹。" ;; *) printf '%s' "--use-existing needs an existing Caravan source folder." ;; esac; }
S_git_is_missing_install_apple_command() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Falta Git. Instala primero las herramientas de línea de comandos de Apple (xcode-select --install) y vuelve a intentarlo." ;; ja) printf '%s' "Git が不足しています。まず Apple Command Line Tools をインストールしてください (xcode-select --install)。その後、再試行してください。" ;; ru) printf '%s' "Git отсутствует. Сначала установи Apple Command Line Tools (xcode-select --install), затем попробуй снова." ;; zh-Hans) printf '%s' "缺少 Git。请先安装 Apple 命令行工具（xcode-select --install），然后重试。" ;; *) printf '%s' "Git is missing. Install Apple Command Line Tools first (xcode-select --install), then retry." ;; esac; }
S_finish_installing_apple_command_line_tools() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Termina de instalar las herramientas de línea de comandos de Apple y vuelve a intentarlo." ;; ja) printf '%s' "Apple Command Line Tools のインストールを完了してから、再試行してください。" ;; ru) printf '%s' "Заверши установку Apple Command Line Tools, затем попробуй снова." ;; zh-Hans) printf '%s' "完成 Apple 命令行工具的安装，然后重试。" ;; *) printf '%s' "Finish installing Apple Command Line Tools, then retry." ;; esac; }
S_reusing_the_mlx_virtual_environment() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se reutiliza el entorno virtual de MLX." ;; ja) printf '%s' "MLX の仮想環境を再利用しています。" ;; ru) printf '%s' "Используется виртуальное окружение MLX." ;; zh-Hans) printf '%s' "复用 MLX 虚拟环境。" ;; *) printf '%s' "Reusing the MLX virtual environment." ;; esac; }
S_existing_venv_is_incompatible_choose_a() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "El entorno virtual existente no es compatible; elige un entorno compatible a mano. No se eliminó." ;; ja) printf '%s' "既存の仮想環境が互換性がないため、手動で互換のある環境を選択してください。削除は行われませんでした。" ;; ru) printf '%s' "Существующая виртуальная среда несовместима; выбери совместимую среду вручную. Она не была удалена." ;; zh-Hans) printf '%s' "现有 venv 不兼容；请手动选择兼容的环境。未删除该环境。" ;; *) printf '%s' "Existing venv is incompatible; choose a compatible environment manually. It was not removed." ;; esac; }
S_installing_tested_dependencies_this_may_use() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Instalando las dependencias comprobadas; esto puede usar internet." ;; ja) printf '%s' "テスト済みの依存関係をインストールしています。インターネットを使用する可能性があります。" ;; ru) printf '%s' "Установка проверенных зависимостей; это может использовать интернет." ;; zh-Hans) printf '%s' "正在安装已测试的依赖项；此过程可能需要使用互联网。" ;; *) printf '%s' "Installing tested dependencies; this may use the internet." ;; esac; }
S_package_dependency_lock_is_missing_download() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Falta el bloqueo de dependencias del paquete. Descarga un paquete actual." ;; ja) printf '%s' "パッケージの依存関係ロックファイルが見つかりません。最新のパッケージをダウンロードしてください。" ;; ru) printf '%s' "Отсутствует файл блокировки зависимостей пакета. Скачай актуальный пакет." ;; zh-Hans) printf '%s' "缺少包依赖锁定文件。请下载当前版本的包。" ;; *) printf '%s' "Package dependency lock is missing. Download a current package." ;; esac; }
S_the_easy_package_needs_its_managed() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "El paquete sencillo necesita su Python 3.12 administrado. Vuelve a ejecutar el instalador de Mac." ;; ja) printf '%s' "Easy パッケージは管理された Python 3.12 を必要とします。Mac のブートストラップを再度実行してください。" ;; ru) printf '%s' "Пакет easy требует управляемого Python 3.12. Запусти заново загрузку Mac." ;; zh-Hans) printf '%s' "easy 包需要其管理的 Python 3.12。请重新运行 Mac 引导程序。" ;; *) printf '%s' "The easy package needs its managed Python 3.12. Rerun the Mac bootstrap." ;; esac; }
S_would_create_a_single_local_mac() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Crearía una configuración de un solo Mac local (sin valores predeterminados de SSH de laboratorio)." ;; ja) printf '%s' "単一ローカル Mac の設定を作成します（ラボ SSH デフォルトなし）。" ;; ru) printf '%s' "Создаётся конфигурация для одного локального Mac (без настроек SSH для лаборатории)." ;; zh-Hans) printf '%s' "将创建单台本地 Mac 配置（无实验室 SSH 默认设置）。" ;; *) printf '%s' "Would create a single-local-Mac config (no lab SSH defaults)." ;; esac; }
S_created_the_local_mac_config_existing() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se creó la configuración del Mac local. Las configuraciones existentes nunca se reemplazan." ;; ja) printf '%s' "ローカル Mac の設定を作成しました。既存の設定は決して置き換えられません。" ;; ru) printf '%s' "Создана конфигурация локального Mac. Существующие конфигурации никогда не заменяются." ;; zh-Hans) printf '%s' "已创建本地 Mac 配置。现有配置永远不会被替换。" ;; *) printf '%s' "Created the local Mac config. Existing configs are never replaced." ;; esac; }
S_an_unrelated_caravan_bin_caravan_exists() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Ya existe un ~/.caravan/bin/caravan que no es de esta instalación. Se conserva; elige otra ruta de comando a mano." ;; ja) printf '%s' "無関係な ~/.caravan/bin/caravan が存在します。そのままにしておいて、手動で別のコマンドパスを選択してください。" ;; ru) printf '%s' "Существует несвязанный ~/.caravan/bin/caravan. Оставь его; выбери другой путь к команде вручную." ;; zh-Hans) printf '%s' "存在无关的 ~/.caravan/bin/caravan。请保留它；手动选择其他命令路径。" ;; *) printf '%s' "An unrelated ~/.caravan/bin/caravan exists. Keep it; choose a different command path manually." ;; esac; }
S_preparing_this_macs_browser_page_so() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Preparando la página del navegador de este Mac para que pueda unirse a tus otros Macs." ;; ja) printf '%s' "この Mac のブラウザページを準備して、他の Mac に参加できるようにしています。" ;; ru) printf '%s' "Готовлю страницу браузера этого Mac, чтобы он мог присоединиться к твоим другим Macам." ;; zh-Hans) printf '%s' "正在准备这台 Mac 的浏览器页面，以便加入你的其他 Mac。" ;; *) printf '%s' "Preparing this Mac’s browser page so it can join your other Macs." ;; esac; }
S_open_a_new_terminal_window_to_2() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Abre una ventana nueva de Terminal para usar caravan (por ejemplo: caravan status)." ;; ja) printf '%s' "新しい Terminal ウィンドウを開いて caravan を使用してください（例：caravan status）。" ;; ru) printf '%s' "Открой новое окно Terminal для использования caravan (например: caravan status)." ;; zh-Hans) printf '%s' "打开一个新的 Terminal 窗口以使用 caravan（例如：caravan status）。" ;; *) printf '%s' "Open a new Terminal window to use caravan (for example: caravan status)." ;; esac; }
S_done_caravan_starts_at_user_login() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Listo. Caravan se inicia al iniciar sesión, no antes. Elige un modelo en el navegador." ;; ja) printf '%s' "完了しました。Caravan はユーザーログイン時に起動し、ログイン前には起動しません。ブラウザでモデルを選択してください。" ;; ru) printf '%s' "Готово. Caravan запускается при входе пользователя, а не до входа. Выбери модель в браузере." ;; zh-Hans) printf '%s' "完成。Caravan 将在用户登录时启动，而不是在登录之前。请在浏览器中选择模型。" ;; *) printf '%s' "Done. Caravan starts at user login, not before login. Choose a model in the browser." ;; esac; }
S_would_ask_whether_to_open_caravan() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Preguntaría si quieres abrir Caravan desde tus otros dispositivos por Tailscale." ;; ja) printf '%s' "Tailscale を通じて他のデバイスから Caravan を開くかどうかを尋ねます。" ;; ru) printf '%s' "Спросит, открыть ли Caravan с других твоих устройств через Tailscale." ;; zh-Hans) printf '%s' "将询问是否通过 Tailscale 从你的其他设备打开 Caravan。" ;; *) printf '%s' "Would ask whether to open Caravan from your other devices over Tailscale." ;; esac; }
S_would_ask_whether_to_open_caravan_2() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Preguntaría si quieres abrir Caravan en tu red local." ;; ja) printf '%s' "ローカルネットワーク上で Caravan を開くかどうかを尋ねます。" ;; ru) printf '%s' "Спросит, открыть ли Caravan в твоей локальной сети." ;; zh-Hans) printf '%s' "将询问是否在你的本地网络上打开 Caravan。" ;; *) printf '%s' "Would ask whether to open Caravan on your local network." ;; esac; }
S_open_http_127_0_0_1() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Abre http://127.0.0.1:${1}/ (navegador local). Para añadir un Mac, elige Añadir Macs. Registros: ~/.caravan/logs/" ;; ja) printf '%s' "http://127.0.0.1:${1}/（ローカルブラウザ）を開いてください。Mac を追加するには「Macs を追加」を選択してください。ログ：~/.caravan/logs/" ;; ru) printf '%s' "Открой http://127.0.0.1:${1}/ (локальный браузер). Чтобы добавить Mac, выбери Добавить Macы. Логи: ~/.caravan/logs/" ;; zh-Hans) printf '%s' "打开 http://127.0.0.1:${1}/（本地浏览器）。要添加 Mac，请选择“添加 Macs”。日志：~/.caravan/logs/" ;; *) printf '%s' "Open http://127.0.0.1:${1}/ (local browser). To add a Mac, choose Add Macs. Logs: ~/.caravan/logs/" ;; esac; }
S_usage_text() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Uso: bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]
       [--python PATH] [--check] [--dry-run] [--no-start] [--update] [--use-existing]
Plan de worker: --model PATH [--counts K,K,... --stage-index I --listen HOST:PORT]
             [--upstream HOST:PORT | --peer HOST:PORT] [--name ID] [--port PORT]
Cada Mac tiene su página en el navegador; un worker de modelo fijo es una opción para desarrolladores." ;; ja) printf '%s' "使用方法: bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]
       [--python PATH] [--check] [--dry-run] [--no-start] [--update] [--use-existing]
Worker プラン: --model PATH [--counts K,K,... --stage-index I --listen HOST:PORT]
             [--upstream HOST:PORT | --peer HOST:PORT] [--name ID] [--port PORT]
各 Mac にはブラウザページが割り当てられます。固定モデルの worker は開発者向けのオプションです。" ;; ru) printf '%s' "Использование: bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]
       [--python PATH] [--check] [--dry-run] [--no-start] [--update] [--use-existing]
План для Worker: --model PATH [--counts K,K,... --stage-index I --listen HOST:PORT]
             [--upstream HOST:PORT | --peer HOST:PORT] [--name ID] [--port PORT]
Каждый Mac получает свою страницу браузера; worker с фиксированной моделью — это опция для разработчика." ;; zh-Hans) printf '%s' "用法：bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]
       [--python PATH] [--check] [--dry-run] [--no-start] [--update] [--use-existing]
Worker 计划：--model PATH [--counts K,K,... --stage-index I --listen HOST:PORT]
             [--upstream HOST:PORT | --peer HOST:PORT] [--name ID] [--port PORT]
每台 Mac 都会获得自己的浏览器页面；固定模型的 worker 是开发选项。" ;; *) printf '%s' "Usage: bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]
       [--python PATH] [--check] [--dry-run] [--no-start] [--update] [--use-existing]
Worker plan: --model PATH [--counts K,K,... --stage-index I --listen HOST:PORT]
             [--upstream HOST:PORT | --peer HOST:PORT] [--name ID] [--port PORT]
Each Mac gets its browser page; a fixed-model worker is a developer option." ;; esac; }
S_would_run() { case "${CARAVAN_UI_LANG}" in es) printf '%s' "Se ejecutaría: " ;; ja) printf '%s' "実行します： " ;; ru) printf '%s' "Запустить бы: " ;; zh-Hans) printf '%s' "将运行：" ;; *) printf '%s' "Would run: " ;; esac; }
# <<< caravan strings <<<
say() { printf '[Caravan] %s\n' "$*"; }
trap 'code=$?; say "$(S_setup_stopped_models_and_existing_settings)" >&2; exit "$code"' ERR
fail() { say "$*" >&2; exit 1; }
usage() {
  printf '%s\n' "$(S_usage_text)"
}
ROLE=lead
WEB_PORT=8190
REPO="$HOME/.caravan/src/caravan"
REF=main
REF_GIVEN=0
PYTHON=""
DRY=0
START=1
UPDATE=0
EXISTING=0
CHECK=0
MODEL=0
STAGE=0
SERVICE_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --check) CHECK=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --no-start) START=0; shift ;;
    --update) UPDATE=1; shift ;;
    --use-existing) EXISTING=1; shift ;;
    --replace-old-services) SERVICE_ARGS+=(--replace-old-services); shift ;;
    --role|--repo|--ref|--python)
      [ "$#" -ge 2 ] || fail "$(S_arg_needs_a_value_2 "$1")"
      case "$1" in
        --role) ROLE=$2 ;; --repo) REPO=$2 ;; --ref) REF=$2; REF_GIVEN=1 ;; --python) PYTHON=$2 ;;
      esac
      shift 2 ;;
    --model|--counts|--stage-index|--listen|--upstream|--peer|--name|--port|--host|--lead-port)
      [ "$#" -ge 2 ] || fail "$(S_arg_needs_a_value_2 "$1")"
      [ "$1" != --model ] || MODEL=1
      case "$1" in --counts|--stage-index|--listen|--upstream|--peer) STAGE=1 ;; esac
      [ "$1" != --port ] || WEB_PORT=$2
      SERVICE_ARGS+=("$1" "$2"); shift 2 ;;
    *) fail "$(S_unknown_option_arg_use_help "$1")" ;;
  esac
done
case "$WEB_PORT" in ''|*[!0-9]*|??????*) fail "$(S_choose_a_port_number_from_1)" ;; esac
[ "$WEB_PORT" -ge 1 ] && [ "$WEB_PORT" -le 65535 ] || fail "$(S_choose_a_port_number_from_1)"
[ "$ROLE" = lead ] || [ "$ROLE" = worker ] || fail "$(S_choose_role_lead_or_role_worker)"
[ "$ROLE" != lead ] || [ "$MODEL" = 0 ] || fail "$(S_install_the_web_ui_as_lead)"
if [ "$ROLE" = worker ] && [ "$MODEL" = 0 ] && [ "$STAGE" = 1 ]; then
  fail "$(S_worker_stage_options_need_an_installed)"
fi
case "$REPO" in /*) ;; *) fail "$(S_repo_must_be_an_absolute_path)" ;; esac
case "$REF" in ''|-*) fail "$(S_ref_must_name_a_git_branch)" ;; esac
[ "$REPO" != / ] && [ "$REPO" != "$HOME" ] || fail "$(S_choose_a_dedicated_caravan_folder_not)"
if [ "$DRY" = 1 ]; then
  say "$(S_preview_only_no_directories_downloads_packag)"
else
  [ "$(uname -s)" = Darwin ] || fail "$(S_this_installer_needs_macos_nothing_was)"
  [ "$(uname -m)" = arm64 ] || fail "$(S_use_an_apple_silicon_mac_and)"
  MACOS=$(sw_vers -productVersion)
  [ "${MACOS%%.*}" -ge 14 ] || fail "$(S_macos_14_or_newer_is_required "$MACOS")"
  [ "$(id -u)" != 0 ] || fail "$(S_run_as_your_normal_macos_user)"
fi
if [ -z "$PYTHON" ]; then
  for candidate in /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$(command -v python3 || true)"; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys;sys.exit(sys.version_info < (3,10))' >/dev/null 2>&1; then
      PYTHON=$candidate; break
    fi
  done
fi
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || fail "$(S_use_the_no_prerequisites_mac_bootstrap)"
"$PYTHON" -c 'import sys;sys.exit(sys.version_info < (3,10))' || fail "$(S_python_3_10_or_newer_is)"
if [ "$DRY" = 0 ]; then
  "$PYTHON" -c 'import platform,sys;sys.exit(platform.machine() != "arm64")' || fail "$(S_this_python_is_running_under_rosetta)"
fi
if [ "$CHECK" = 1 ]; then
  exec "$PYTHON" "$(cd "$(dirname "$0")/.." && pwd)/tools/caravan_doctor.py" --port "$WEB_PORT"
fi
if [ "$DRY" = 0 ]; then
  FREE=$(df -Pk "$HOME" | awk 'END {print $4}')
  [ "$FREE" -ge 8388608 ] || fail "$(S_free_at_least_8_gb_before)"
fi
say "$(S_python_python "$PYTHON")"
say "$(S_source_folder_repo_ref "$REPO" "$REF")"
run() {
  if [ "$DRY" = 1 ]; then printf '[Caravan] %s' "$(S_would_run)"; printf '%q ' "$@"; printf '\n'; else "$@"; fi
}
# Reuse matching checkouts. Never reset, force, change branches or overwrite work.
if [ -d "$REPO/.git" ]; then
  REMOTE=$(git -C "$REPO" remote get-url origin)
  case "$REMOTE" in https://github.com/linuxbren/caravan.git|git@github.com:linuxbren/caravan.git|https://github.com/linuxbren/caravan) ;;
    *) fail "$(S_that_checkout_has_a_different_origin)" ;;
  esac
  [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "$(S_your_checkout_has_local_changes_keep)"
  CURRENT=$(git -C "$REPO" symbolic-ref --short -q HEAD || git -C "$REPO" describe --tags --exact-match HEAD || true)
  # Checkouts made before Day 30 follow an old branch name. Those branches are
  # fast-forwarded to main with every release, so keep pulling the branch the
  # checkout is on instead of refusing it (no branch is switched).
  if [ "$REF_GIVEN" = 0 ] && [ "$CURRENT" != "$REF" ]; then
    case "$CURRENT" in caravan-v3-mlx-split|clean-install-fixes)
      say "$(S_this_checkout_follows_the_old_branch "$CURRENT")"
      REF=$CURRENT ;;
    esac
  fi
  [ "$CURRENT" = "$REF" ] || fail "$(S_checkout_is_current_not_ref_no "$CURRENT" "$REF")"
  if [ "$UPDATE" = 1 ]; then
    git -C "$REPO" symbolic-ref -q HEAD >/dev/null || fail "$(S_a_release_tag_is_immutable_choose)"
    run git -C "$REPO" pull --ff-only origin "$REF"
  else
    say "$(S_matching_clean_checkout_found_leaving_its)"
  fi
elif [ -e "$REPO" ]; then
  if [ "$EXISTING" = 1 ] && [ -f "$REPO/proxy/web_server.py" ] && [ -f "$REPO/tools/caravan_service.py" ]; then
    say "$(S_using_existing_extracted_source_no_git)"
  else
    fail "$(S_that_folder_already_exists_and_is)"
  fi
else
  [ "$EXISTING" = 0 ] || fail "$(S_use_existing_needs_an_existing_caravan)"
  if [ "$DRY" = 0 ]; then
    command -v git >/dev/null || fail "$(S_git_is_missing_install_apple_command)"
    git --version >/dev/null || fail "$(S_finish_installing_apple_command_line_tools)"
  fi
  run mkdir -p "$(dirname "$REPO")"
  run git clone --branch "$REF" --single-branch https://github.com/linuxbren/caravan.git "$REPO"
fi
VENV="$HOME/.caravan/venvs/mlx"
if [ ! -x "$VENV/bin/python" ]; then
  run "$PYTHON" -m venv "$VENV"
else
  say "$(S_reusing_the_mlx_virtual_environment)"
  if [ "$DRY" = 0 ]; then
    "$VENV/bin/python" -c 'import sys,platform;sys.exit(sys.version_info < (3,10) or platform.machine() != "arm64")' || fail "$(S_existing_venv_is_incompatible_choose_a)"
  fi
fi
say "$(S_installing_tested_dependencies_this_may_use)"
if [ -f "$REPO/.caravan-package" ]; then
  [ -f "$REPO/requirements-mac.lock" ] || fail "$(S_package_dependency_lock_is_missing_download)"
  "$PYTHON" -c 'import sys;sys.exit(sys.version_info[:2] != (3,12))' || fail "$(S_the_easy_package_needs_its_managed)"
  run "$VENV/bin/python" -m pip install --only-binary=:all: -r "$REPO/requirements-mac.lock"
else
  # Developer source installs retain the documented Python 3.10+ path.
  run "$VENV/bin/python" -m pip install -r "$REPO/requirements-mac.txt"
fi
run "$VENV/bin/python" -m pip check
run "$VENV/bin/python" -c 'import mlx.core, mlx_lm, huggingface_hub, spake2, cryptography;print("Mac environment imports OK")'
run "$VENV/bin/python" "$REPO/agent/llama_runtime.py"
run "$VENV/bin/python" "$REPO/tools/caravan_path.py" install
# Every fresh browser install gets a single-local-node config. Never replace existing settings.
CONFIG="$HOME/.caravan/config.toml"
FRESH_CONFIG=0
if { [ "$ROLE" = lead ] || [ "$MODEL" = 0 ]; } && [ ! -e "$CONFIG" ]; then
  FRESH_CONFIG=1
  if [ "$DRY" = 1 ]; then
    say "$(S_would_create_a_single_local_mac)"
  else
    mkdir -p "$HOME/.caravan"
    (set -o noclobber; printf '%s\n' '[defaults]' 'self_tune = "auto"' '' '[web.nodes.local]' 'label = "My Mac"' 'role = "lead"' 'host = "local"' > "$CONFIG")
    say "$(S_created_the_local_mac_config_existing)"
  fi
fi
# Stable command location; only publish after successful install/preparation.
register_command() {
if [ "$DRY" = 0 ]; then
  mkdir -p "$HOME/.caravan/bin"
  WRAPPER="$HOME/.caravan/bin/caravan"
  if [ -e "$WRAPPER" ] && ! /usr/bin/grep -q '^# Caravan managed command$' "$WRAPPER"; then
    fail "$(S_an_unrelated_caravan_bin_caravan_exists)"
  fi
  { printf '%s\n' '#!/bin/bash' '# Caravan managed command'; printf 'exec %q %q "$@"\n' "$VENV/bin/python" "$REPO/tools/caravan.py"; } > "$WRAPPER"
  chmod 755 "$WRAPPER"
  if [ -f "$REPO/.caravan-package" ]; then printf '%s\n' "$ROLE" > "$REPO/.caravan-role"; fi
fi
}
if [ "$ROLE" = lead ]; then
  KIND=web
elif [ "$MODEL" = 1 ]; then
  KIND=worker
else
  KIND=web
  say "$(S_preparing_this_macs_browser_page_so)"
fi
SERVICE=("$VENV/bin/python" "$REPO/tools/caravan_service.py" install --kind "$KIND" --repo "$REPO" --python "$VENV/bin/python")
if [ "$START" = 0 ]; then SERVICE+=(--no-start); fi
if [ "$DRY" = 1 ]; then
  SERVICE+=(--dry-run)
  run "${SERVICE[@]}" ${SERVICE_ARGS[@]+"${SERVICE_ARGS[@]}"}
else
  "${SERVICE[@]}" ${SERVICE_ARGS[@]+"${SERVICE_ARGS[@]}"}
fi
register_command
say "$(S_open_a_new_terminal_window_to_2)"
say "$(S_done_caravan_starts_at_user_login)"
if [ "$KIND" = web ]; then
  if [ "$FRESH_CONFIG" = 1 ]; then run "$VENV/bin/python" "$REPO/tools/caravan_pairing.py" prepare; fi
  # Optional questions, only on a fresh install. Tailscale is asked only if
  # it is ready and a terminal can be read (/dev/tty under curl|bash).
  # The local-network question is always offered on a fresh install when a
  # terminal can be read; default is No. Updates never ask. Otherwise silent.
  if [ "$FRESH_CONFIG" = 1 ] && [ "$UPDATE" = 0 ]; then
    if [ "$DRY" = 1 ]; then
      say "$(S_would_ask_whether_to_open_caravan)"
      say "$(S_would_ask_whether_to_open_caravan_2)"
    else
      "$VENV/bin/python" "$REPO/tools/caravan_remote.py" maybe-prompt --port "$WEB_PORT"
      "$VENV/bin/python" "$REPO/tools/caravan_lan.py" maybe-prompt --port "$WEB_PORT"
    fi
  fi
  say "$(S_open_http_127_0_0_1 "$WEB_PORT")"
fi
