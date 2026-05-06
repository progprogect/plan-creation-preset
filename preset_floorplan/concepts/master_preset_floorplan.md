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
7. Для **technical_bw / v2**: список **оборудования** — для каждого: `id`, подпись, габарит `bbox` (x, y, width, height, rotation) или `polygon`; способ детализации: **`library_key`** (например `conveyor_linear`, `robot_cell`, `packing_block`, …), или **`parametric_symbol`** (примитивы `line|rect|circle|polyline|hatch_rect` в локальных координатах габарита), или **`external_svg`** (путь к файлу / XML-фрагмент).
8. Нумерованные **выноски** (`annotations.callouts`): id, текст, привязка `target_id` к `equipment.id` или точка `anchor`, смещение `offset`.
9. Тип зоны помещения `zone_type`: `production` | `storage` | `other` (у **storage** в technical_bw — штриховка).
10. Дополнительно: отдельные **стены** (`walls`).

После ответов сформируй валидный JSON (`version: 1` или **2**; для оборудования — **2**), `rooms[]` без самопересечений, и передай в `spec_json`.

## Мастер-оркестрация
1. Вход: `spec_json` — строка JSON по канонической модели (см. `preset_floorplan/schema/floorplan_spec.schema.json` и концепт `domain_floorplan_geometry_export`).
2. Рекомендуемый единый вызов: эксперт **`floorplan_build_pipeline`** — валидация → SVG → при необходимости PDF/PNG.
3. Атомарные эксперты (опционально): `floorplan_spec_validate`, `floorplan_render_svg`, `floorplan_export_pdf`, `floorplan_export_png` — для отладки или частичного конвейера.

## CSPL
По умолчанию **`fython`** для всех экспертов пресета. **`parallel_task`** имеет смысл только при пакетной генерации множества планов (не входит в MVP).

## Каноническая модель (кратко)
- `version`: **1** (схема) или **2** (+ `equipment`, `annotations`; при v1 эти поля игнорируются с предупреждением).
- `units`: **`mm` | `cm` | `m`**
- `title`: заголовок на чертеже
- `rooms[]`: `id`, `name`, `polygon`, опционально **`zone_type`**: `production` | `storage` | `other`
- `walls[]` (опционально): отрезки + `thickness`
- `openings[]` (опционально, MVP): зарезервировано
- **`equipment[]` (v2)**: габарит `bbox` или `polygon`, `representation`: `library_key` | `parametric_symbol` | `external_svg`
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
- Публикация в аккаунт Extella: `python preset_floorplan/scripts/bootstrap_api.py` при установленном `EXTELLA_API_TOKEN`.
- Примеры: `preset_floorplan/examples/*.json`

## Параметры `floorplan_build_pipeline`
- `spec_json` (string): полная спецификация JSON.
- `outputs` (string): через запятую, например `pdf,png,svg` (по умолчанию все три).
- `output_dir` (string): каталог для файлов (пусто — системный temp).
- `dpi` (int): для PNG (по умолчанию 150).
- `page_size` (string): `A4` (по умолчанию).
- `orientation` (string): `landscape` | `portrait` (по умолчанию `landscape`).
