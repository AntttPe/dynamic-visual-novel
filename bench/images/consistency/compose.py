"""Składanie sceny w wariancie layers: tło lokacji + wycięte postacie, jak w visual novel.

Tło to obraz wzorcowy lokacji (rysowany raz, w grze brany z cache po location_id). Postacie są wycinane
z neutralnego tła modelem rembg (isnet-general-use, działa na CPU) i ustawiane obok siebie przy dolnej krawędzi.
rembg zapisuje swój model w U2NET_HOME (na serwerze: ~/data/cache/u2net, README).
"""

import os
from pathlib import Path


class Composer:
    def __init__(self):
        self.session = None

    def compose(self, background: Path, sprites: list[Path], out: Path, size: tuple[int, int]) -> dict:
        from PIL import Image
        from rembg import new_session, remove

        if self.session is None:
            os.environ.setdefault("U2NET_HOME", str(Path("~/data/cache/u2net").expanduser()))
            self.session = new_session("isnet-general-use")
        width, height = size
        scene = Image.open(background).convert("RGB").resize(size)
        n = len(sprites)
        for i, path in enumerate(sprites):
            cut = remove(Image.open(path).convert("RGB"), session=self.session)
            box = cut.getbbox()
            if box:
                cut = cut.crop(box)
            scale = 0.85 * height / cut.height
            cut = cut.resize((max(1, round(cut.width * scale)), round(cut.height * scale)))
            x = round((i + 1) * width / (n + 1) - cut.width / 2)
            y = round(0.98 * height) - cut.height
            scene.paste(cut, (x, y), cut)
        scene.save(out)
        return {"sprites": n}


class FakeComposer:
    """Do testów: zapisuje mały plik zamiast obrazu."""

    def __init__(self):
        self.calls: list[dict] = []

    def compose(self, background: Path, sprites: list[Path], out: Path, size: tuple[int, int]) -> dict:
        self.calls.append({"background": str(background), "sprites": [str(s) for s in sprites]})
        out.write_bytes(b"fake composed")
        return {"sprites": len(sprites)}
