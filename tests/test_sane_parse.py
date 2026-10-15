from v500capture.scanners.sane_cli import parse_options, pick_mode, pick_resolution, range_max

# Trimmed `scanimage -A` output from the epkowa backend with a V500.
EPKOWA = """
All options specific to device `epkowa:interpreter:002:003':
  Scan Mode:
    --mode Binary|Gray|Color [Color]
        Selects the scan mode (e.g., lineart, monochrome, or color).
    --depth 8|16 [8]
        Number of bits per sample.
    --resolution 50..6400dpi [400]
        Sets the resolution of the scanned image.
    --source Flatbed|Transparency Unit [Flatbed]
        Selects the scan source.
    --film-type Positive Film|Negative Film [inactive]
  Geometry:
    -l 0..215.9mm [0]
        Top-left x position of scan area.
    -t 0..297.18mm [0]
    -x 0..215.9mm [215.9]
    -y 0..297.18mm [297.18]
"""


def test_parse_options():
    opts = parse_options(EPKOWA)
    assert opts["--mode"] == "Binary|Gray|Color"
    assert opts["--resolution"] == "50..6400dpi"
    assert "--film-type" not in opts  # inactive
    assert range_max(opts["-x"]) == 215.9 and range_max(opts["-y"]) == 297.18


def test_pick_mode():
    assert pick_mode("Binary|Gray|Color", "color") == "Color"
    assert pick_mode("Binary|Gray|Color", "bw") == "Binary"
    assert pick_mode("Lineart|Gray|Color", "bw") == "Lineart"
    assert pick_mode("Lineart|Grayscale|24bit Color", "gray") == "Grayscale"
    assert pick_mode("Lineart|Grayscale|24bit Color", "color") == "24bit Color"
    assert pick_mode(None, "color") is None


def test_pick_resolution():
    assert pick_resolution("50..6400dpi", 300) == 300
    assert pick_resolution("50..600dpi", 1200) == 600
    assert pick_resolution("75|150|300|600dpi", 400) == 300
    assert pick_resolution("75|150|300|600dpi", 500) == 600
    assert pick_resolution(None, 300) == 300


def test_max_resolution():
    from v500capture.scanners.sane_cli import max_resolution

    assert max_resolution("50..6400dpi") == 6400
    assert max_resolution("75|150|300|600dpi") == 600
    assert max_resolution(None) is None
