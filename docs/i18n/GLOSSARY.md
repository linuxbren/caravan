# Localization glossary

Words Caravan reuses a lot, so every language file can stay consistent.
Spanish (Day 32) is neutral Latin American / universal Spanish, with the
casual *tú* tone the English text already has. Russian (Day 32) is
natural Russian with the informal *ты* tone. Japanese (Day 32) is
natural, polite-casual Japanese (です/ます in help text and sentences;
short button labels). Model names, the product
name **Caravan**, **Mini**, **GGUF**, **MLX**, command lines and code
identifiers stay in English. Feature names **Guess-ahead** and
**Balance** stay in English.

| English | Spanish | Russian | Japanese | Notes |
|---|---|---|---|---|
| model | modelo | модель | モデル | A model on disk or in the catalog. |
| Models | Modelos | Модели | モデル | The catalog drawer. |
| split | reparto / repartir | распределение / распределить | 分割 / 分割する | Running one model across more than one Mac. |
| layers | capas | слои | レイヤー | Model layers on a Mini. |
| tokens | tokens | tokens | tokens | Kept in English; usual in this field. |
| token | token | token | token | Same. |
| context | contexto | контекст | コンテキスト | The model's context window (Day 31 wording). |
| quant | cuantización | квантование | 量子化 | When it names a file or a row in the catalog, "quant" may stay as a short label if it is next to a technical name. Spanish running text uses "cuantización"; Russian running text uses "квантование", and catalog counts use квант / кванта / квантов. Japanese running text uses 量子化; a short catalog label may stay quant. |
| Load | Cargar | Загрузить | 読み込む | Button. Cloud models also say Cargar / Загрузить, not Descargar / Скачать. |
| Download | Descargar | Скачать | ダウンロード | Button. |
| Unload | Descargar de memoria | Выгрузить из памяти | メモリから外す | Not the same as Descargar / Скачать (a file). If space is tight: "Quitar" / "Убрать". Prefer the longer form in help text and the short form on a tight button. Japanese: prefer メモリから外す in help; 外す on a tight button. |
| Settings | Ajustes | Настройки | 設定 | The right-hand drawer. |
| Mini | Mini | Mini | Mini | Stays English. Plural: Minis. |
| Mac | Mac | Mac | Mac | Stays English. Plural: Macs. In Russian, "this Mac" is "этот Mac" (masculine). In Japanese, "this Mac" is "この Mac". |
| Caravan | Caravan | Caravan | Caravan | Product name, never translated. |
| GGUF, MLX | GGUF, MLX | GGUF, MLX | GGUF, MLX | Format names, never translated. |
| Chat | chat | чат | チャット | The conversation view. |
| Queue | Cola | Очередь | キュー | The Send button while a reply is written. |
| Stop | Detener | Остановить | 停止 | Ends the reply on the Macs. |
| Update | Actualizar | Обновить | 更新 |  |
| Topology | Топология | Топология | トポロジー |  |
| placement | ubicación | размещение | 配置 | Where a model runs (1 Mini / split / copy to all). |
| Copy to all | Copiar a todos | Скопировать на все | すべてにコピー |  |
| recommended | recomendado | рекомендуется | おすすめ |  |
| beta | beta | beta | beta | Mark on a language in the picker until a native speaker reviews it. The picker shows "Español (beta)" and "Русский (beta)", and "日本語 (beta)". |
| Apply & restart | Aplicar y reiniciar | Применить и перезапустить | 適用して再起動 |  |
| Auto-tune | Autoajuste | Автонастройка | 自動調整 |  |
| Self-tuning | Autoajuste | Автонастройка | 自動調整 |  |
| hugging face / Hugging Face | Hugging Face | Hugging Face | Hugging Face | Product name. |
| Ollama Cloud | Ollama Cloud | Ollama Cloud | Ollama Cloud | Product name. |
| tailnet / Tailscale | Tailscale | Tailscale | Tailscale | Product name; "tu red de Tailscale" / "твоя сеть Tailscale" in running text. |
| Remote Login | Inicio de sesión remoto | Удалённый вход | リモートログイン | macOS setting name, explained in the language. |
| on / off | activado / desactivado | включено / выключено | オン / オフ | Switches. Short: Sí / No is too vague; prefer Activado / Desactivado or включено / выключено. |

Numbers in Spanish use a decimal comma and a period as the thousands
separator (1.234,5). Lists of words use "y" and "o". Dates look like
"13 de noviembre" and "noviembre de 2026".

Numbers in Russian use a decimal comma and a space as the thousands
separator (1 234,5). Lists of words use "и" and "или". Dates look like
"13 ноября" (genitive month) and "ноябрь 2026" (nominative month).
Russian count strings use the CLDR forms one / few / many / other
(1 модель, 2 модели, 5 моделей, 1,5 модели).

Numbers in Japanese use a decimal period and a comma as the thousands
separator (1,234.5). Lists of words use 、 and と (a、bとc). Dates look like
2026年11月13日 and 2026年11月. Japanese count strings use the CLDR `other`
form only ({n}件のモデル).
