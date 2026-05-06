# Пресет Extella: план помещения и экспорт PDF/PNG/SVG (мастер-концепт)

## Назначение
Один пресет для генерации схематичного плана помещений из **структурированного JSON** (без CAD/BIM-уровня). Исполнение экспертов — **локально в ExTella**. Вызовы API (`/api/expert/save`, `/api/expert/run`) — по стандартной схеме Extella; **токены и ключи не хранить в концептах**, только в KV Store или переменных окружения.

## Что спросить у пользователя в начале
Перед сборкой `spec_json` и вызовом **`floorplan_build_pipeline`** уточни:

1. **Единицы** чертежа: `mm`, `cm` или `m` (все координаты в одних единицах).
2. **Форматы вывода**: нужны ли `svg`, `pdf`, `png` (можно несколько через запятую).
3. **Куда сохранить файлы**: путь к папке или оставить пустым для системного temp.
4. **Заголовок плана** (`title`) и **список помещений**: для каждого — имя (`name`), ориентировочная форма (прямоугольник, L-образ, несколько прямоугольников) и **размеры или вершины** в выбранных единицах; либо пользователь даёт **готовый JSON** по схеме.
5. **Сетка** на плане: нужна ли (`show_grid`), при необходимости **шаг** `grid_step`; для техрежима — подписи осей (`show_coord_grid`).
6. **Режим чертежа**: схема цветных блоков (`style.render_profile: schematic`, **version 1**) или **инженерно-графический ч/б** (`technical_bw`, желательно **version 2**).
7. Для **technical_bw / v2**: список **оборудования** — для каждого: `id`, подпись, габарит `bbox` (x, y, width, height, rotation) или `polygon`; способ детализации: **`library_key`** (например `conveyor_linear`, `robot_cell`, `packing_block`, …), или **`parametric_symbol`** (примитивы `line|rect|circle|polyline|hatch_rect` в локальных координатах габарита), или **`external_svg`** (путь к файлу / XML-фрагмент), или **`external_raster`** (PNG: `path` или `data_uri` для вставки в SVG).
8. Нумерованные **выноски** (`annotations.callouts`): id, текст, привязка `target_id` к `equipment.id` или точка `anchor`, смещение `offset`.
9. Тип зоны помещения `zone_type`: `production` | `storage` | `other` (у **storage** в technical_bw — штриховка).
10. Дополнительно: отдельные **стены** (`walls`).

После ответов сформируй валидный JSON (`version: 1` или **2**; для оборудования — **2**), `rooms[]` без самопересечений, и передай в `spec_json`.

## Какой эксперт вызывать (главное — без дублирования)

Имена экспертов фиксированы; **не придумывай** другие. Модель **`gpt-image-2`** (GPT Image 2, 2026) — для **генерации изображений** через OpenAI Images API. Это **не** «GPT‑2»: GPT‑2 — старая **текстовая** модель и к картинкам не относится.

| Ситуация | Единственный вызов (если не просят «пошагово») |
|----------|-----------------------------------------------|
| У пользователя уже есть **готовый `spec_json`** | **`floorplan_build_pipeline`** |
| Нужно из **текста ТЗ** получить план, PNG узлов (опц.) и экспорт SVG/PDF/PNG | **`floorplan_full_openai_pipeline`** |
| Черновик **layout_draft** уже есть строкой JSON (не из Chat этого пресета) | **`floorplan_layout_draft_merge`**, затем при необходимости `floorplan_openai_equipment_images` и **`floorplan_build_pipeline`** |

**Запрещённая плохая последовательность:** сначала **`floorplan_openai_layout`**, потом **`floorplan_full_openai_pipeline`** на то же ТЗ — второй снова делает разметку, двойная работа и путаница в логах.

**Пошаговая отладка** (только если пользователь явно просит разбить): `floorplan_openai_layout` → `floorplan_openai_equipment_images` → `floorplan_build_pipeline` → при необходимости `floorplan_openai_overview_image`.

Параметр **`image_model`** у экспертов с картинками: по умолчанию **`gpt-image-2`**. Если аккаунт/тариф не принимает эту модель, можно передать **`dall-e-3`** (резерв).

## Мастер-оркестрация (JSON уже есть)
1. Вход: `spec_json` — строка JSON по канонической модели (см. `preset_floorplan/schema/floorplan_spec.schema.json` и концепт `domain_floorplan_geometry_export`).
2. **Один** вызов: **`floorplan_build_pipeline`** — валидация → SVG → при необходимости PDF/PNG.
3. Атомарные эксперты только для отладки: `floorplan_spec_validate`, `floorplan_render_svg`, `floorplan_export_pdf`, `floorplan_export_png`.

## Многошаговый пайплайн с OpenAI (текст → план)
Ключ **OpenAI** не вставлять в текст концепта: только **KV Store** (`OPENAI_API_KEY`) или параметр `openai_api_key` у эксперта.

**Схема черновика раскладки:** `preset_floorplan/schema/layout_draft.schema.json` (версия черновика `version: 1`).

**Нормальный путь:** один вызов **`floorplan_full_openai_pipeline`** — внутри: Chat → layout/spec → (опц.) изображения узлов через **`image_model`** (по умолчанию `gpt-image-2`) → экспорт. Если в **`outputs`** есть **`png`**, по умолчанию (**`final_png_from_openai` = true**) итоговый **`paths.png`** — **один кадр из OpenAI Images** (промпт из нормализованного spec, **1536×1024**), без растровки SVG через Cairo/matplotlib. Каноническая геометрия — в **`paths.svg`** (и PDF при необходимости). Старое повечение PNG из вектора: **`final_png_from_openai` = false**. Отдельный вызов **`floorplan_layout_draft_merge`** при этом **не** нужен.

Зависимость в ExTella: `extella-pip install openai` (актуальный SDK; для `gpt-image-2` может понадобиться обновление пакета).

## CSPL
По умолчанию **`fython`** для всех экспертов пресета. **`parallel_task`** имеет смысл только при пакетной генерации множества планов (не входит в MVP).

## Почему в UI «ничего не изменилось»
- **Концепт:** `POST /api/concept/add` каждый раз создаёт **новую** запись с **новым id**. Если агент привязан к **старому** id концепта, он продолжит видеть старый текст. Обновить текст **на месте**: `POST /api/concept/update` с тем же `concept_id` (в репозитории: `bootstrap_api.py --master-concept-id <id>`).
- **Эксперты:** `save` должен перезаписывать код по **имени**. Если подозрение на кэш/рассинхрон, перед сохранением выполнить `DELETE /api/expert/delete/<name>` (`bootstrap_api.py --delete-experts`).
- **Агент:** проверить, что у агента в профиле подключены эксперты с теми же **именами**, что в пресете (`floorplan_build_pipeline`, …).

## Публикация в Extella (репозиторий)
```text
python preset_floorplan/scripts/embed_experts.py
EXTELLA_API_TOKEN=… python preset_floorplan/scripts/bootstrap_api.py \\
  --delete-experts \\
  --master-concept-id <ваш_id_мастера> \\
  --domain-concept-id <ваш_id_домена>
```
Без id концептов скрипт сделает **add** (новые id). С id — **update** (текст заменится у существующих записей).

## Каноническая модель (кратко)
- `version`: **1** (схема) или **2** (+ `equipment`, `annotations`; при v1 эти поля игнорируются с предупреждением).
- `units`: **`mm` | `cm` | `m`**
- `title`: заголовок на чертеже
- `rooms[]`: `id`, `name`, `polygon`, опционально **`zone_type`**: `production` | `storage` | `other`
- `walls[]` (опционально): отрезки + `thickness`
- `openings[]` (опционально, MVP): зарезервировано
- **`equipment[]` (v2)**: габарит `bbox` или `polygon`, `representation`: `library_key` | `parametric_symbol` | `external_svg` | **`external_raster`** (`path` к PNG или `data_uri`)
- **`annotations.callouts[]` (v2)**: выноски к оборудованию или к точке
- `style.render_profile`: **`schematic`** | **`technical_bw`**; `style.technical` — толщины, штриховка склада

Пример техрежима: `preset_floorplan/examples/production_line_technical_v2.json`.

## Ограничения MVP
- Схематичный / CAD-light чертёж, **не** полный BIM/ГОСТ.
- Детализация проёмов (двери/окна) — в следующих версиях.
- Экспорт PDF/PNG опирается на **Cairo/CairoSVG** при наличии; иначе — SVG гарантирован, PNG через **matplotlib** как fallback из исходного spec.

## Файлы пресета в репозитории
- Схема: `preset_floorplan/schema/floorplan_spec.schema.json`
- Реализация: `preset_floorplan/python/floorplan_core.py`
- Готовые тела экспертов: `preset_floorplan/experts/*.py` (пересобрать после правок ядра: `python preset_floorplan/scripts/embed_experts.py`).
- Публикация в аккаунт Extella: см. раздел «Публикация в Extella» выше (`bootstrap_api.py`, при необходимости `--delete-experts` и `--master-concept-id`).
- Примеры: `preset_floorplan/examples/*.json`

## Параметры `floorplan_build_pipeline`
- `spec_json` (string): полная спецификация JSON.
- `outputs` (string): через запятую, например `pdf,png,svg` (по умолчанию все три).
- `output_dir` (string): каталог для файлов (пусто — системный temp).
- `dpi` (int): для PNG (по умолчанию 150).
- `page_size` (string): `A4` (по умолчанию).
- `orientation` (string): `landscape` | `portrait` (по умолчанию `landscape`).
