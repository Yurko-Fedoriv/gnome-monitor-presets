// Display identity comes from the EDID vendor; retain the full spec for matching.
const brands = {
    GSM: 'LG', LGD: 'LG', MSI: 'MSI', SAM: 'Samsung', DEL: 'Dell',
    ACI: 'ASUS', AUS: 'ASUS', ACR: 'Acer', BNQ: 'BenQ', HWP: 'HP',
    HPN: 'HP', LEN: 'Lenovo', PHL: 'Philips', AOC: 'AOC', APP: 'Apple',
    VSC: 'ViewSonic', EIZ: 'EIZO', ENC: 'EIZO', SNY: 'Sony',
};

export function monitorName(spec, connector = spec[0]) {
    const vendor = spec[1]?.trim();
    const brand = brands[vendor?.toUpperCase()] ?? vendor;
    return brand ? `${connector} · ${brand}` : connector;
}
