# Localization glossary

Words Caravan reuses a lot, so every language file can stay consistent.
Spanish (Day 32) is neutral Latin American / universal Spanish, with the
casual *tú* tone the English text already has. Russian (Day 32) is
natural Russian with the informal *ты* tone. Model names, the product
name **Caravan**, **Mini**, **GGUF**, **MLX**, command lines and code
identifiers stay in English. Feature names **Guess-ahead** and
**Balance** stay in English.

| English | Spanish | Russian | Notes |
|---|---|---|---|
| model | modelo | модель | A model on disk or in the catalog. |
| Models | Modelos | Модели | The catalog drawer. |
| split | reparto / repartir | распределение / распределить | Running one model across more than one Mac. |
| layers | capas | слои | Model layers on a Mini. |
| tokens | tokens | tokens | Kept in English; usual in this field. |
| token | token | token | Same. |
| context | contexto | контекст | The model's context window (Day 31 wording). |
| quant | cuantización | квантование | When it names a file or a row in the catalog, "quant" may stay as a short label if it is next to a technical name. Spanish running text uses "cuantización"; Russian running text uses "квантование", and catalog counts use квант / кванта / квантов. |
| Load | Cargar | Загрузить | Button. Cloud models also say Cargar / Загрузить, not Descargar / Скачать. |
| Download | Descargar | Скачать | Button. |
| Unload | Descargar de memoria | Выгрузить из памяти | Not the same as Descargar / Скачать (a file). If space is tight: "Quitar" / "Убрать". Prefer the longer form in help text and the short form on a tight button. |
| Settings | Ajustes | Настройки | The right-hand drawer. |
| Mini | Mini | Mini | Stays English. Plural: Minis. |
| Mac | Mac | Mac | Stays English. Plural: Macs. In Russian, "this Mac" is "этот Mac" (masculine). |
| Caravan | Caravan | Caravan | Product name, never translated. |
| GGUF, MLX | GGUF, MLX | GGUF, MLX | Format names, never translated. |
| Chat | chat | чат | The conversation view. |
| Queue | Cola | Очередь | The Send button while a reply is written. |
| Stop | Detener | Остановить | Ends the reply on the Macs. |
| Update | Actualizar | Обновить | |
| Topology | Топология | Топология | |
| placement | ubicación | размещение | Where a model runs (1 Mini / split / copy to all). |
| Copy to all | Copiar a todos | Скопировать на все | |
| recommended | recomendado | рекомендуется | |
| beta | beta | beta | Mark on a language in the picker until a native speaker reviews it. The picker shows "Español (beta)" and "Русский (beta)". |
| Apply & restart | Aplicar y reiniciar | Применить и перезапустить | |
| Auto-tune | Autoajuste | Автонастройка | |
| Self-tuning | Autoajuste | Автонастройка | |
| hugging face / Hugging Face | Hugging Face | Hugging Face | Product name. |
| Ollama Cloud | Ollama Cloud | Ollama Cloud | Product name. |
| tailnet / Tailscale | Tailscale | Tailscale | Product name; "tu red de Tailscale" / "твоя сеть Tailscale" in running text. |
| Remote Login | Inicio de sesión remoto | Удалённый вход | macOS setting name, explained in the language. |
| on / off | activado / desactivado | включено / выключено | Switches. Short: Sí / No is too vague; prefer Activado / Desactivado or включено / выключено. |

Numbers in Spanish use a decimal comma and a period as the thousands
separator (1.234,5). Lists of words use "y" and "o". Dates look like
"13 de noviembre" and "noviembre de 2026".

Numbers in Russian use a decimal comma and a space as the thousands
separator (1 234,5). Lists of words use "и" and "или". Dates look like
"13 ноября" (genitive month) and "ноябрь 2026" (nominative month).
Russian count strings use the CLDR forms one / few / many / other
(1 модель, 2 модели, 5 моделей, 1,5 модели).
