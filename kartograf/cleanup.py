from pathlib import Path

def cleanup_rpki_files(context):
    """
    Removes intermediate RPKI output files.
    """
    files_to_remove = [ "rpki_raw.json" ]

    for filename in files_to_remove:
        file_path = Path(context.out_dir_rpki) / filename

        _try_remove(file_path)


def cleanup_irr_files(context):
    """
    Removes intermediate IRR output files.
    """
    files_to_remove = [ "afrinic.db", "apnic.db.route", "apnic.db.route6", "arin.db", "irr_filtered.txt", "lacnic.db", "ripe.db.route", "ripe.db.route6" ]

    for filename in files_to_remove:
        file_path = Path(context.out_dir_irr) / filename

        _try_remove(file_path)


def cleanup_collectors_files(context):
    """
    Removes intermediate collector output files.
    """
    files_to_remove = [
        "pfx2asn.txt",
        "pfx2asn_clean.txt",
        "routeviews_pfx2asn_ip4.txt",
        "routeviews_pfx2asn_ip6.txt",
    ]

    for filename in files_to_remove:
        file_path = Path(context.out_dir_collectors) / filename
        try:
            if file_path.exists():
                file_path.unlink()
        except FileNotFoundError as e:
            print(f"Error removing {filename}: {e}")


def _try_remove(file_path):
    try:
        if file_path.exists():
            file_path.unlink()
    except FileNotFoundError:
        print(f"File not found on cleanup: {file_path}")
