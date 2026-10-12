"""Post-processing: tidy a recovered folder (repair, names, dates, duplicates)."""
from __future__ import annotations

from salvage.post.base import PostContext, PostStep
from salvage.post.dedupe import Dedupe
from salvage.post.names import DateNames, OriginalNames
from salvage.post.partial import PartialPhotos

# run order matters: repaired copies get names too; dedupe sees final names
STEPS: dict[str, type] = {s.name: s for s in (PartialPhotos, OriginalNames, DateNames, Dedupe)}
DEFAULT_STEPS = list(STEPS)


def run_steps(ctx: PostContext, names: list[str] | None = None) -> dict:
    """Run the named steps in their standard order, saving the manifest after each."""
    names = DEFAULT_STEPS if names is None else names
    unknown = set(names) - set(STEPS)
    if unknown:
        raise ValueError(f"unknown post-processing step(s): {', '.join(sorted(unknown))} "
                         f"(available: {', '.join(STEPS)})")
    results = {}
    for name in DEFAULT_STEPS:
        if name not in names:
            continue
        step: PostStep = STEPS[name]()
        ctx.events.emit("phase", name=step.title)
        results[name] = step.run(ctx)
        ctx.manifest.save()
    return results


__all__ = ["PostContext", "PostStep", "STEPS", "DEFAULT_STEPS", "run_steps",
           "PartialPhotos", "OriginalNames", "DateNames", "Dedupe"]
