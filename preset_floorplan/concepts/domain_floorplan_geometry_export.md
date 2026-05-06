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
- Chat (JSON strict): эксперт **`floorplan_openai_layout`**. Images: **`floorplan_openai_equipment_images`**, **`floorplan_openai_overview_image`**. Полный конвейер: **`floorplan_full_openai_pipeline`**.
`conveyor_linear`, `robot_cell`, `tank`, `workstation`, `pallet_conveyor`, `packing_block`, `stretch_wrapper`, `generic` (fallback).

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
