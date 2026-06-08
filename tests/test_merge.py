'''
Test merging multiple sets of networks, as if they were independent AS files.
'''
from pathlib import Path
from types import SimpleNamespace
import pytest

from kartograf.merge import general_merge, merge_irr, merge_pfx2as, pick_chunk_size

from .util.generate_data import (
    build_file_lines,
    generate_ip_file,
    generate_file_items,
    generate_asns,
    generate_subnets_from_base,
    make_disjoint
)


def _tmp_paths(tmp_path):
    return [tmp_path / p for p in ["rpki_final.txt", "irr_final.txt", "out.txt"]]

def _read_test_vectors(filepath):
    '''
    Fixtures for IP networks are under tests/data.
    Read them and return the list of valid networks and the list of individual subnets in the file.
    '''
    all_networks = []
    all_in_result = []
    with open(filepath, "r") as f:
        lines = f.readlines()[1:]
        for line in lines:
            network, in_result, _comment = line.split(',')
            all_networks.append(network)
            if in_result.strip() == "1":
                all_in_result.append(network)
    return all_networks, all_in_result

def test_merge_from_fixtures(tmp_path):
    '''
    Assert that general_merge merges subnets correctly,
    and validates against expected networks,
    i.e. subnets are merged into the root network appropriately.
    '''
    data_dir = Path(__file__).parent / "data"
    base_nets, base_results = _read_test_vectors(data_dir / "base_file.csv")
    base_path = tmp_path / "base.txt"
    extra_nets, extra_results = _read_test_vectors(data_dir / "extra_file.csv")
    extra_path = tmp_path / "extra.txt"
    # write the networks to disk, generating ASNs for each network
    generate_ip_file(base_path, build_file_lines(base_nets, generate_asns(len(base_nets))))
    generate_ip_file(extra_path, build_file_lines(extra_nets, generate_asns(len(extra_nets))))

    outpath = tmp_path / "final_result.txt"
    general_merge(base_path, extra_path, None, outpath)
    with open(outpath, "r") as f:
        l = f.readlines()
        merged_networks = sorted([line.split()[0] for line in l])
    expected_networks = sorted(base_results + extra_results)
    # Compare the merged result of networks, excluding duplicates and subnets,
    # with the expected results
    assert merged_networks == expected_networks

@pytest.mark.parametrize("ip_type", ["v4", "v6"])
def test_merge_identical_files(tmp_path, ip_type):
    '''
    Assert that merging two identical files is a no-op.
    '''
    rpki_data = generate_file_items(100, ip_type=ip_type)
    rpki_path, _, out_path = _tmp_paths(tmp_path)
    generate_ip_file(rpki_path, rpki_data)

    general_merge(rpki_path, rpki_path, None, out_path)

    with open(out_path, "r") as f:
        lines = f.readlines()
        final_ips = [item.split()[0] for item in lines]
        assert lines == rpki_data
        assert len(final_ips) == len(rpki_data)


def test_merge_disjoint(tmp_path):
    '''
    Test merging non-overlapping sets of IP networks.
    '''
    main_data = generate_file_items(100)
    main_ips = [item.split()[0] for item in main_data]
    rpki_ips = main_ips[:50]
    irr_ips = main_ips[50:]
    irr_ips = make_disjoint(rpki_ips, irr_ips)
    rpki_data = build_file_lines(rpki_ips, generate_asns(len(rpki_ips)))
    irr_data = build_file_lines(irr_ips, generate_asns(len(irr_ips)))

    rpki_path, irr_path, out_path = _tmp_paths(tmp_path)
    generate_ip_file(rpki_path, rpki_data)
    generate_ip_file(irr_path, irr_data)
    general_merge(rpki_path, irr_path, None, out_path)

    with open(out_path, "r") as f:
        lines = f.readlines()
        final_ips = [item.split()[0] for item in lines]

    assert set(final_ips) == (set(irr_ips) | set(rpki_ips))


def test_merge_rpki_supersedes_irr_subnets(tmp_path):
    '''
    Test that RPKI networks take priority over overlapping IRR subnets.
    '''
    overlap = 10
    rpki_data = generate_file_items(100)
    rpki_ips = [item.split()[0] for item in rpki_data]
    # generate subnets of the rpki networks that should get merged into the base file
    irr_ips = generate_subnets_from_base(rpki_ips, overlap)
    irr_data = build_file_lines(irr_ips, generate_asns(len(irr_ips)))

    rpki_path, irr_path, out_path = _tmp_paths(tmp_path)
    generate_ip_file(rpki_path, rpki_data)
    generate_ip_file(irr_path, irr_data)
    general_merge(rpki_path, irr_path, None, out_path)

    with open(out_path, "r") as f:
        lines = f.readlines()
        final_ips = [item.split()[0] for item in lines]

    assert set(final_ips).isdisjoint(set(irr_ips)), (
        f"IRR subnets should not appear in merged output: {set(final_ips) & set(irr_ips)}"
    )


def test_three_file_merge_irr_supersedes_routeviews_more_specific(tmp_path):
    '''
    Test the full RPKI -> IRR -> Routeviews merge sequence.

    A Routeviews more-specific prefix must not be included when it is covered
    by an IRR prefix, otherwise Routeviews would supersede IRR under longest
    prefix match semantics.
    '''
    out_dir = tmp_path
    out_dir_rpki = tmp_path / "rpki"
    out_dir_irr = tmp_path / "irr"
    out_dir_collectors = tmp_path / "collectors"
    out_dir_rpki.mkdir()
    out_dir_irr.mkdir()
    out_dir_collectors.mkdir()

    # RPKI has a more-specific prefix whose network address is the same as
    # the broader IRR prefixes below. The old merge implementation must not
    # treat this RPKI /22 as covering the IRR /8 or /9.
    (out_dir_rpki / "rpki_final.txt").write_text("10.0.0.0/8 AS64500\n12.0.0.0/22 AS6269\n")
    (out_dir_irr / "irr_final.txt").write_text("12.0.0.0/8 AS7018\n12.0.0.0/9 AS7018\n")
    (out_dir_collectors / "pfx2asn_clean.txt").write_text(
        "12.0.0.0/8 AS7018\n"
        "12.0.0.0/9 AS7018\n"
        "12.2.12.0/24 AS40724\n"
        "13.0.0.0/8 AS1239\n"
    )

    context = SimpleNamespace(
        out_dir=out_dir,
        out_dir_rpki=out_dir_rpki,
        out_dir_irr=out_dir_irr,
        out_dir_collectors=out_dir_collectors,
        final_result_file=tmp_path / "final_result.txt",
        cleanup_out_files=[],
        args=SimpleNamespace(irr=True),
    )

    merge_irr(context)
    merge_pfx2as(context)

    result = context.final_result_file.read_text()

    assert "10.0.0.0/8 AS64500\n" in result
    assert "12.0.0.0/22 AS6269\n" in result
    assert "12.0.0.0/8 AS7018\n" in result
    assert "12.0.0.0/9 AS7018\n" in result
    assert "13.0.0.0/8 AS1239\n" in result
    assert "12.2.12.0/24 AS40724\n" not in result


def test_pick_chunk_size():
    '''
    Test picking a chunk size for the merge function.
    '''
    assert pick_chunk_size(100, workers=16) == 7
    assert pick_chunk_size(100, workers=4) == 25
    # min_chunk wins
    assert pick_chunk_size(10, workers=4) == 5
    # min_chunk wins
    assert pick_chunk_size(0) == 5
