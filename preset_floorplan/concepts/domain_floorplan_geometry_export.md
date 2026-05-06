# Геометрия плана и экспорт (предметный концепт)

## Валидация
- Использовать **Shapely** для проверки полигонов комнат: `Polygon(coords).is_valid`; при невалидности — явная ошибка `invalid_polygon` с пояснением.
- Удалять дублирующее замыкание последней точки, если совпадает с первой.
- Единицы `units` не конвертируются в MVP между разными полями — все координаты в одних и тех же пользовательских единицах.

## Рендер
- **`schematic`** (по умолчанию): цветные заливки комнат, палитра, сетка по `show_grid`.
- **`technical_bw`**: ч/б линии, штриховка зон `storage`, сетка и при `show_coord_grid` — подписи осей, оборудование через `library_key` / `parametric_symbol` / `external_svg` / **`external_raster`** (PNG в габарите), выноски `annotations.callouts`.
- Артефакт — **SVG** (svgwrite), затем при необходимости PDF/PNG.

## Черновик раскладки (layout_draft)
- JSON по схеме `layout_draft.schema.json`: `version: 1`, `units`, `rooms[]`, опционально `equipment[]` с полями `bbox`, `text_description` (промпт для картинки узла).
- Слияние в канонический spec: функция `merge_layout_draft_to_spec` / эксперт **`floorplan_layout_draft_merge`**. В spec попадает `representation.openai_image_hint` до генерации PNG.

## Растровые символы (external_raster)
- В `representation.external_raster`: **`path`** — абсолютный или относительный путь к PNG/WebP (рендер подставляет `file://` URI); или **`data_uri`** (`data:image/png;base64,...`), разумный лимит размера.
- При наличии валидного растра векторные примитивы узла из `library_key`/`parametric_symbol` для этого элемента **не рисуются** (только картинка в том же transform, что и SVG-символы).

## OpenAI
- **Оркестрация:** по тексту ТЗ обычно достаточно **одного** эксперта **`floorplan_full_openai_pipeline`** (внутри Chat + при необходимости картинки + экспорт). Не цеплять **`floorplan_openai_layout`** перед ним на то же ТЗ.
- Chat (строгий JSON): **`floorplan_openai_layout`** или шаг внутри full pipeline. Images: **`floorplan_openai_equipment_images`**, **`floorplan_openai_overview_image`**.
- Модель **картинок** по умолчанию: **`gpt-image-2`** (GPT Image 2); резерв **`dall-e-3`**. Не путать с **GPT‑2** (текст).
- В **`floorplan_full_openai_pipeline`** при **`outputs`**, содержащем **`png`**, итоговый **`paths.png`** по умолчанию — **OpenAI Images** по полному промпту из spec; точные размеры и привязки — в **`paths.svg`**.
- Эксперт слияния черновика: **`floorplan_layout_draft_merge`** — если `layout_draft` уже есть снаружи.
- Справочник `library_key`: `conveyor_linear`, `robot_cell`, `tank`, `workstation`, `pallet_conveyor`, `packing_block`, `stretch_wrapper`, `generic`.

## Параметрический слой
Примитивы: `line`, `rect`, `circle`, `polyline`, `hatch_rect`; не более **300** на единицу оборудования.

## Экспорт PDF/PNG
- Предпочтительно: **CairoSVG** (`svg2pdf`, `svg2png`) для соответствия вектор ↔ растр.
- **Риски окружения**: на части Windows-сборок возможны отсутствующие DLL для Cairo — документировать и отдавать `cairo_missing`, оставляя SVG.
- **Fallback PNG**: перерисовка того же spec через **matplotlib** в PNG (без Cairo), чтобы пользователь получил растр.

## Шрифты
- Для согласованности между PDF и PNG: предпочтительно дефолтные шрифты Cairo/matplotlib; встраивание шрифтов — расширение.

## Что не кладём в концепт
Секреты API, пути к личным файлам пользователя, токены — только в KV Store / параметры.
