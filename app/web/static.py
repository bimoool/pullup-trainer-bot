"""StaticFiles с разными Cache-Control для index.html и хешированных assets.

По умолчанию Starlette отдаёт статику только с etag/last-modified, без
Cache-Control — Telegram Mini App клиенты (особенно мобильные) агрессивно
кэшируют index.html без должной ревалидации, и задеплоенный фикс физически
лежит на сервере, но не доходит до пользователя (issue #27). Vite кладёт
хешированные по содержимому файлы бандла в assets/ (имя меняется при каждой
пересборке — их можно и нужно кэшировать надолго), а index.html и прочие
нехешированные файлы из public/ — в корень dist/, их нельзя кэшировать
вообще, раз это входная точка SPA (или файл, который может измениться без
смены имени).
"""

from os import stat_result
from pathlib import Path

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_NO_STORE_CACHE_CONTROL = "no-store"


class CacheControlStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: str,
        stat_result: stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        is_hashed_asset = "assets" in Path(full_path).parts
        response.headers["Cache-Control"] = (
            _IMMUTABLE_CACHE_CONTROL if is_hashed_asset else _NO_STORE_CACHE_CONTROL
        )
        return response
