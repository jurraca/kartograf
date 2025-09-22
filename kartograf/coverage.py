import ipaddress
import polars as pl
from tqdm import tqdm


def coverage(map_file, ip_list_file):

    rpki_nets = []
    rpki_masks = []
    for line in map_file:
        pfx, _ = line.split()
        try:
            ipn = ipaddress.ip_network(pfx)
        except ValueError:
            raise ValueError(f"""
                  Invalid IP network provided: {line}
                  Please remove and re-run.
                  """)

        netw = int(ipn.network_address)
        mask = int(ipn.netmask)
        rpki_masks.append(mask)
        rpki_nets.append(netw)

    # Create list of (mask, network_address) tuples for coverage checking
    zipped = list(zip(rpki_masks, rpki_nets))

    addrs = []
    for line in ip_list_file:
        try:
            ip = ipaddress.ip_address(line.rstrip('\n'))
            addrs.append(int(ip))
        except ValueError:
            raise ValueError(f"""
                  Invalid IPv4/IPv6 address provided: {line}.
                  Please remove and re-run.
                  """)

    df = pl.DataFrame({
        'ADDRS': addrs
    }, schema={
        'ADDRS': pl.Object  # Use Object type to handle large IPv6 integers
    })

    def check_coverage(addr):
        for mask, net_addr in zipped:
            if (addr & mask) == net_addr:
                return 1
        return 0

    # Apply coverage check with progress tracking
    print("Checking IP coverage...")
    covered_results = []
    for addr in tqdm(addrs, desc="Checking coverage"):
        covered_results.append(check_coverage(addr))
    
    df = df.with_columns(pl.Series("COVERED", covered_results))
    df_cov = df.filter(pl.col("COVERED") == 1)

    covered = len(df_cov)
    total = len(df)
    percentage = (covered / total) * 100
    print(f"A total of {covered} IPs out of {total} are covered by the map. "
          f"That's {percentage:.2f}%")
