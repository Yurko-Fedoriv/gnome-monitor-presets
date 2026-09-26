"""Pure display conversion: no desktop access or filesystem mutations."""
import copy


def identity(spec):
    return tuple(spec[1:])


def snapshot(state):
    _, monitors, logical, properties = state
    physical = {m[0][0]: m for m in monitors}
    result = {"layout_mode": properties.get("layout-mode", 1), "logical": [],
              "connected": [list(m[0]) for m in monitors],
              "leased": [list(m[0]) for m in monitors if m[2].get("is-for-lease", False)]}
    for x, y, scale, transform, primary, specs, _ in logical:
        group = {"x": x, "y": y, "scale": scale, "transform": transform,
                 "primary": primary, "monitors": []}
        for spec in specs:
            _, modes, props = physical[spec[0]]
            mode = next((m for m in modes if m[6].get("is-current")), None)
            if mode is None:
                raise ValueError(f"No current mode for {spec[0]}")
            options = {k: props[k] for k in ("color-mode", "rgb-range") if k in props}
            if "is-underscanning" in props:
                options["underscanning"] = props["is-underscanning"]
            group["monitors"].append({"spec": list(spec), "mode": mode[0],
                "width": mode[1], "height": mode[2], "refresh": mode[3],
                "refresh_mode": mode[6].get("refresh-rate-mode", "fixed"),
                "interlaced": mode[6].get("is-interlaced", False), "options": options})
        result["logical"].append(group)
    if not result["logical"]:
        raise ValueError("Cannot save a layout with no active displays")
    return result


def match_monitor(spec, monitors):
    matches = [m for m in monitors if identity(m[0]) == identity(spec)]
    exact = [m for m in matches if m[0][0] == spec[0]]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Required monitor {spec[2]} ({spec[0]}) is missing or ambiguous")


def resolve(saved, state):
    """Resolve identities and exact modes afresh; never degrade to preferred mode."""
    _, monitors, _, props = state
    result = copy.deepcopy(saved)
    used = set()
    if not result["logical"] or sum(g["primary"] for g in result["logical"]) != 1:
        raise ValueError("A layout must have active displays and exactly one primary")
    if (saved["layout_mode"] != props.get("layout-mode", 1)
            and not props.get("supports-changing-layout-mode", False)):
        raise ValueError("Saved layout mode is unsupported")
    for group in result["logical"]:
        for monitor in group["monitors"]:
            live = match_monitor(monitor["spec"], monitors)
            if live[0][0] in used:
                raise ValueError("A monitor is assigned more than once")
            used.add(live[0][0])
            modes = [m for m in live[1] if m[1] == monitor["width"]
                and m[2] == monitor["height"] and abs(m[3] - monitor["refresh"]) < 0.001
                and m[6].get("refresh-rate-mode", "fixed") == monitor["refresh_mode"]
                and m[6].get("is-interlaced", False) == monitor["interlaced"]]
            mode = next((m for m in modes if m[0] == monitor["mode"]), None)
            if mode is None and len(modes) == 1:
                mode = modes[0]
            if mode is None:
                raise ValueError(f"Exact saved mode unavailable on {live[0][0]}")
            if not any(abs(s - group["scale"]) < 0.00001 for s in mode[5]):
                raise ValueError(f"Saved scale unavailable on {live[0][0]}")
            options = monitor["options"]
            if "color-mode" in options and options["color-mode"] not in live[2].get("supported-color-modes", [0]):
                raise ValueError(f"Saved color mode unavailable on {live[0][0]}")
            if "underscanning" in options and "is-underscanning" not in live[2]:
                raise ValueError(f"Underscanning unavailable on {live[0][0]}")
            monitor["spec"] = list(live[0])
            monitor["mode"] = mode[0]
    result["leased"] = [list(match_monitor(spec, monitors)[0]) for spec in saved.get("leased", [])]
    return result


def signature(saved):
    """Ignore monitor enumeration order, labels, and ephemeral mode identifiers."""
    groups = []
    for g in saved["logical"]:
        ms = sorted((identity(m["spec"]), m["width"], m["height"], round(m["refresh"], 3),
                     m["refresh_mode"], m["interlaced"], tuple(sorted(m["options"].items())))
                    for m in g["monitors"])
        groups.append((g["x"], g["y"], round(g["scale"], 5), g["transform"], g["primary"], ms))
    return (saved["layout_mode"], sorted(groups), sorted(identity(s) for s in saved.get("leased", [])),
            saved.get("preferences", {}), saved.get("backlights", []))
