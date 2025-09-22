from pathlib import Path
import ipaddress
import shutil
import polars as pl

from kartograf.timed import timed
from kartograf.util import get_root_network


class BaseNetworkIndex:
    '''
    A class whose _dict represents a mapping of the network number and
    IP networks within that network for a given AS file.

    To check inclusion of a given IP network in the base AS file,
    we can compare (see check_inclusion) the networks under the root network number
    instead of all the networks in the base file.
    '''


    def __init__(self):
        self._dict = {4: {}, 6: {}}
        self._v4_keys = self._dict[4].keys()
        self._v6_keys = self._dict[6].keys()

    def update(self, pfx):
        try:
            ipn = ipaddress.ip_network(pfx)
        except ValueError:
            print(f"Invalid prefix provided: {pfx}")
            return

        netw = int(ipn.network_address)
        mask = int(ipn.netmask)
        v = ipn.version
        root_net = get_root_network(pfx)

        if root_net in self._dict[v]:
            current = self._dict[v][root_net]
            self._dict[v][root_net] = current + [(netw, mask)]
        else:
            self._dict[v].update({root_net: [(netw, mask)]})

    def check_inclusion(self, row, root_net, version):
        """
        A network is a subnet of another if the bitwise AND of its IP and the base network's netmask
        is equal to the base network IP.
        """
        for net, mask in self._dict[version][root_net]:
            if row['INETS'] & mask == net:
                return 1
        return 0

    def contains_row(self, row):
        # Handle both pandas-style named tuples and polars-style dictionaries
        root_net = row['PFXS_LEADING']
        pfxs = row['PFXS']

        version = ipaddress.ip_network(pfxs).version
        if version == 4 and (root_net in self._v4_keys):
            return self.check_inclusion(row, root_net, version)
        if version == 6 and (root_net in self._v6_keys):
            return self.check_inclusion(row, root_net, version)
        return 0


@timed
def merge_irr(context):
    rpki_file = Path(context.out_dir_rpki) / "rpki_final.txt"
    irr_file = Path(context.out_dir_irr) / "irr_final.txt"
    irr_filtered_file = Path(context.out_dir_irr) / "irr_filtered.txt"
    out_file = Path(context.out_dir) / "merged_file_rpki_irr.txt"
    context.cleanup_out_files += [irr_filtered_file, out_file]

    general_merge(
        rpki_file,
        irr_file,
        irr_filtered_file,
        out_file
    )
    shutil.copy2(out_file, context.final_result_file)


@timed
def merge_pfx2as(context):
    # We are always doing RPKI but IRR is optional for now so depending on this
    # we are working off of a different base file for the merge.
    if context.args.irr:
        base_file = Path(context.out_dir) / "merged_file_rpki_irr.txt"
        out_file = Path(context.out_dir) / "merged_file_rpki_irr_rv.txt"
    else:
        base_file = Path(context.out_dir_rpki) / "rpki_final.txt"
        out_file = Path(context.out_dir) / "merged_file_rpki_rv.txt"

    rv_file = Path(context.out_dir_collectors) / "pfx2asn_clean.txt"
    rv_filtered_file = Path(context.out_dir_collectors) / "pfx2asn_filtered.txt"
    context.cleanup_out_files += [rv_filtered_file, out_file]

    general_merge(
        base_file,
        rv_file,
        rv_filtered_file,
        out_file
    )
    shutil.copy2(out_file, context.final_result_file)


def extra_file_to_df(extra_file_path):
    extra_nets_int = []
    extra_asns = []
    extra_pfxs = []
    extra_pfxs_leading = []
    with open(extra_file_path, "r") as file:
        for line in file:
            pfx, asn = line.split(" ")
            try:
                ipn = ipaddress.ip_network(pfx)
            except ValueError:
                print(f"Invalid IP network: {pfx}, skipping")
                continue
            netw_int = int(ipn.network_address)
            extra_nets_int.append(netw_int)
            extra_asns.append(asn.strip())
            extra_pfxs.append(pfx)
            root_net = get_root_network(pfx)
            extra_pfxs_leading.append(root_net)

    df_extra = pl.DataFrame({
        "INETS": extra_nets_int,
        "ASNS": extra_asns,
        "PFXS": extra_pfxs,
        "PFXS_LEADING": extra_pfxs_leading
        }, schema={
        "INETS": pl.Object,  # Use Object type to handle large IPv6 integers
        "ASNS": pl.String,
        "PFXS": pl.String,
        "PFXS_LEADING": pl.Int64
        })

    return df_extra


def general_merge(
    base_file, extra_file, extra_filtered_file, out_file
):
    """
    Merge lists of IP networks into a base file.
    """
    print("Parse base file to dictionary")
    base = BaseNetworkIndex()
    with open(base_file, "r") as file:
        for line in file:
            pfx, _ = line.split(" ")
            base.update(pfx)

    print("Parse extra file to Polars DataFrame")
    df_extra = extra_file_to_df(extra_file)

    print("Merging extra prefixes that were not included in the base file.")
    # Convert to list of named tuples for compatibility with contains_row
    extra_included = []
    for row in df_extra.iter_rows(named=True):
        result = base.contains_row(row)
        extra_included.append(result)

    df_extra = df_extra.with_columns(pl.Series("INCLUDED", extra_included))
    df_filtered = df_extra.filter(pl.col("INCLUDED") == 0)

    print("Finished merging extra prefixes.")

    if extra_filtered_file:
        print(
            f"Finished filtering! Originally {len(df_extra)} "
            f"entries filtered down to {len(df_filtered)}"
        )
        df_filtered.select(["PFXS", "ASNS"]).write_csv(
            extra_filtered_file,
            separator=" ",
            include_header=False
        )

        with open(extra_filtered_file, "r") as extra:
            extra_contents = extra.read()
    else:
        print(
            f"Finished filtering! Originally {len(df_extra)} entries "
            f"filtered down to {len(df_filtered)}"
        )
        # Use StringIO to get CSV content as string
        import io
        buffer = io.StringIO()
        df_filtered.select(["PFXS", "ASNS"]).write_csv(
            buffer, separator=" ", include_header=False
        )
        extra_contents = buffer.getvalue()
        buffer.close()

    print("Merging base file with filtered extra file")
    with open(base_file, "r") as base:
        base_contents = base.read()

    with open(out_file, "w") as merge_file:
        merge_file.write(base_contents + extra_contents)
