import ipaddress
import pandas as pd
from kartograf.merge import BaseNetworkIndex

def test_base_dict_create():
    base = BaseNetworkIndex()
    state = base.get()
    assert state == {4: {}, 6: {}}

def test_base_dict_update():
    base = BaseNetworkIndex()
    state = base.get()
    network = "10.10.0.0/16"
    base.update(network)
    assert state[4][10]
    assert len(list(state[4][10])) == 1


def test_check_inclusion():
    base = BaseNetworkIndex()
    network = "10.10.0.0/16"
    base.update(network)
    subnet = "10.10.0.0/21"
    network_int = int(ipaddress.ip_network(subnet).network_address)
    df_extra = pd.DataFrame(
        data={
        "INETS": network_int,
        "ASNS": 345,
        "PFXS": subnet,
        "PFXS_LEADING": 10},
        index=[0])
    for row in df_extra.itertuples(index=False):
        assert base.contains_row(row)

