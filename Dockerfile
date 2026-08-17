# Shade Route — container image.
#
# Every pinned version in requirements.txt has a cp313 manylinux wheel, so this
# needs no compiler and no GDAL system packages: geopandas, shapely and pyproj
# all ship their native libraries inside the wheel. That is why the base can be
# `slim` rather than a multi-hundred-megabyte geo image.
FROM python:3.13-slim

# Non-root, because the platforms that run this (Hugging Face Spaces in
# particular) mount the working directory as a normal user.
RUN useradd -m -u 1000 app
WORKDIR /app

# Dependencies first, so a code change does not re-resolve the whole geo stack.
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# The OSM caches are committed and copied in deliberately. Without them the
# first request would hit the Overpass API, which is a shared public service
# that went unreachable for half an hour during this build — not something a
# judge opening the link should be gambling on.
COPY --chown=app:app . .

USER app

# HF Spaces reads app_port from its README; Render and Cloud Run inject $PORT.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands at runtime rather than being passed literally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
