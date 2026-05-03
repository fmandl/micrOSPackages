"""
GSM7 / UCS2 / PDU codec for SIM800 SMS handling.
"""


GSM7_BASIC = {
    0x00: '@', 0x01: '£', 0x02: '$', 0x03: '¥', 0x04: 'è', 0x05: 'é', 0x06: 'ù', 0x07: 'ì',
    0x08: 'ò', 0x09: 'Ç', 0x0A: '\n', 0x0B: 'Ø', 0x0C: 'ø', 0x0D: '\r', 0x0E: 'Å', 0x0F: 'å',
    0x10: 'Δ', 0x11: '_', 0x12: 'Φ', 0x13: 'Γ', 0x14: 'Λ', 0x15: 'Ω', 0x16: 'Π', 0x17: 'Ψ',
    0x18: 'Σ', 0x19: 'Θ', 0x1A: 'Ξ', 0x1B: None,
    0x1C: 'Æ', 0x1D: 'æ', 0x1E: 'ß', 0x1F: 'É',
    0x20: ' ', 0x21: '!', 0x22: '"', 0x23: '#', 0x24: '¤', 0x25: '%', 0x26: '&', 0x27: "'",
    0x28: '(', 0x29: ')', 0x2A: '*', 0x2B: '+', 0x2C: ',', 0x2D: '-', 0x2E: '.', 0x2F: '/',
    0x30: '0', 0x31: '1', 0x32: '2', 0x33: '3', 0x34: '4', 0x35: '5', 0x36: '6', 0x37: '7',
    0x38: '8', 0x39: '9', 0x3A: ':', 0x3B: ';', 0x3C: '<', 0x3D: '=', 0x3E: '>', 0x3F: '?',
    0x40: '¡', 0x41: 'A', 0x42: 'B', 0x43: 'C', 0x44: 'D', 0x45: 'E', 0x46: 'F', 0x47: 'G',
    0x48: 'H', 0x49: 'I', 0x4A: 'J', 0x4B: 'K', 0x4C: 'L', 0x4D: 'M', 0x4E: 'N', 0x4F: 'O',
    0x50: 'P', 0x51: 'Q', 0x52: 'R', 0x53: 'S', 0x54: 'T', 0x55: 'U', 0x56: 'V', 0x57: 'W',
    0x58: 'X', 0x59: 'Y', 0x5A: 'Z', 0x5B: 'Ä', 0x5C: 'Ö', 0x5D: 'Ñ', 0x5E: 'Ü', 0x5F: '§',
    0x60: '¿', 0x61: 'a', 0x62: 'b', 0x63: 'c', 0x64: 'd', 0x65: 'e', 0x66: 'f', 0x67: 'g',
    0x68: 'h', 0x69: 'i', 0x6A: 'j', 0x6B: 'k', 0x6C: 'l', 0x6D: 'm', 0x6E: 'n', 0x6F: 'o',
    0x70: 'p', 0x71: 'q', 0x72: 'r', 0x73: 's', 0x74: 't', 0x75: 'u', 0x76: 'v', 0x77: 'w',
    0x78: 'x', 0x79: 'y', 0x7A: 'z', 0x7B: 'ä', 0x7C: 'ö', 0x7D: 'ñ', 0x7E: 'ü', 0x7F: 'à'
}

GSM7_EXT = {
    0x0A: '\f', 0x14: '^', 0x28: '{', 0x29: '}', 0x2F: '\\', 0x3C: '[', 0x3D: '~',
    0x3E: ']', 0x40: '|', 0x65: '€'
}

# Reverse common Hungarian carrier substitutions
GSM7_HU_POST = {
    'à': 'á', 'ò': 'ó', 'ù': 'ú',
    'À': 'Á', 'Ò': 'Ó', 'Ù': 'Ú',
}


def number_to_semi_octet(number):
    """Encode phone number to semi-octet PDU format."""
    digits = number.lstrip('+')
    if len(digits) % 2:
        digits += 'F'
    return ''.join(digits[i+1] + digits[i] for i in range(0, len(digits), 2))


def semi_octet_to_number(hex_str):
    """Decode semi-octet PDU format to phone number string."""
    s = hex_str.strip().upper()
    swapped = ''.join(s[i+1] + s[i] for i in range(0, len(s)-1, 2))
    if len(s) % 2 == 1:
        swapped += s[-1]
    if swapped.endswith('F'):
        swapped = swapped[:-1]
    return swapped


def swap_pairs(hex_str):
    """Swap adjacent hex character pairs."""
    return ''.join(hex_str[i+1] + hex_str[i] for i in range(0, len(hex_str), 2))


def ceil_even_int(n):
    """Round up to nearest even integer."""
    return n + (n & 1)


def pad_hex(h):
    """Pad hex string to even length, strip spaces."""
    h2 = h.replace(" ", "")
    return h2 if len(h2) % 2 == 0 else "0" + h2


def is_gsm7_encodable(text):
    """Check if text can be encoded in GSM7 default alphabet."""
    gsm7_chars = {v for v in GSM7_BASIC.values() if v is not None}
    ext_chars = set(GSM7_EXT.values())
    return all(ch in gsm7_chars or ch in ext_chars for ch in text)


def encode_gsm7(text):
    """Encode text to GSM7 septets and packed bytes.
    :return tuple: (septet list, packed bytearray)
    """
    GSM7_REV = {v: k for k, v in GSM7_BASIC.items() if v is not None}
    GSM7_EXT_REV = {v: k for k, v in GSM7_EXT.items()}
    septets = []
    for ch in text:
        if ch in GSM7_EXT_REV:
            septets.append(0x1B)
            septets.append(GSM7_EXT_REV[ch])
        else:
            septets.append(GSM7_REV.get(ch, 0x3F))  # '?' for unknown
    bit_acc = 0
    num_bits = 0
    result = bytearray()
    for s in septets:
        bit_acc |= s << num_bits
        num_bits += 7
        while num_bits >= 8:
            result.append(bit_acc & 0xFF)
            bit_acc >>= 8
            num_bits -= 8
    if num_bits > 0:
        result.append(bit_acc & 0xFF)
    return septets, result


def decode_gsm7(user_data_hex, septet_len, fill_bits=0):
    """Decode GSM7 packed data to text.
    :param user_data_hex str: hex-encoded packed GSM7 data
    :param septet_len str: number of septets as hex string
    :param fill_bits int: UDH fill bits to skip
    :return str: decoded text
    """
    data = bytes.fromhex(pad_hex(user_data_hex))
    septet_len = int(septet_len, 16)
    bit_acc = 0
    bits_in_acc = 0
    out_chars = []
    byte_index = 0
    if fill_bits > 0:
        while bits_in_acc < fill_bits and byte_index < len(data):
            bit_acc |= data[byte_index] << bits_in_acc
            bits_in_acc += 8
            byte_index += 1
        bit_acc >>= fill_bits
        bits_in_acc -= fill_bits
    while len(out_chars) < septet_len:
        while bits_in_acc < 7 and byte_index < len(data):
            bit_acc |= data[byte_index] << bits_in_acc
            bits_in_acc += 8
            byte_index += 1
        if bits_in_acc == 0:
            break
        septet = bit_acc & 0x7F
        bit_acc >>= 7
        bits_in_acc -= 7
        if septet == 0x1B:
            while bits_in_acc < 7 and byte_index < len(data):
                bit_acc |= data[byte_index] << bits_in_acc
                bits_in_acc += 8
                byte_index += 1
            if bits_in_acc == 0:
                break
            ext_val = bit_acc & 0x7F
            bit_acc >>= 7
            bits_in_acc -= 7
            out_chars.append(GSM7_EXT.get(ext_val, '?'))
        else:
            out_chars.append(GSM7_BASIC.get(septet, '?'))
    return ''.join(out_chars)


def decode_utf16be_with_surrogates(b):
    """Decode UTF-16BE bytes with surrogate pair support."""
    chars = []
    i = 0
    while i < len(b):
        if i + 1 >= len(b):
            break
        code_unit = (b[i] << 8) | b[i+1]
        i += 2
        if 0xD800 <= code_unit <= 0xDBFF:
            if i + 1 >= len(b):
                chars.append('?')
                break
            next_code_unit = (b[i] << 8) | b[i+1]
            i += 2
            if 0xDC00 <= next_code_unit <= 0xDFFF:
                code_point = ((code_unit - 0xD800) << 10) + (next_code_unit - 0xDC00) + 0x10000
                chars.append(chr(code_point))
            else:
                chars.append('?')
                i -= 2
        else:
            chars.append(chr(code_unit))
    return ''.join(chars)


def decode_8bit_data(h, tp_udl=None):
    """Decode 8-bit data from hex string."""
    b = bytes.fromhex(pad_hex(h.strip()))
    if tp_udl is not None:
        tp_udl = int(tp_udl, 16)
        b = b[:tp_udl] if tp_udl <= len(b) else b + b'\x00' * (tp_udl - len(b))
    return b


def decode_ussd_ucs2(hex_str):
    """Decode UCS2 hex string from USSD response."""
    try:
        return bytes.fromhex(hex_str).decode('utf-16-be')
    except Exception:
        return hex_str


def time_zone_offset(hex_str):
    """Parse timezone offset from PDU timestamp byte."""
    raw = int(hex_str, 16)
    sign = "-" if raw & 0x80 else "+"
    minutes = (int(swap_pairs(hex_str), 16) & 0x7F) * 15
    return f"{sign}{minutes//60:02d}:{minutes%60:02d}"


def time_stamp_parse(hex_str):
    """Parse PDU timestamp to human-readable string."""
    swapped = swap_pairs(hex_str)
    tz = time_zone_offset(hex_str[12:14])
    return f"20{swapped[0:2]}-{swapped[2:4]}-{swapped[4:6]} {swapped[6:8]}:{swapped[8:10]}:{swapped[10:12]} {tz}"


def parse_udh(user_data_hex):
    """Parse User Data Header from hex string.
    :return tuple: (udh_dict, user_data_hex_without_udh) or (None, original_hex)
    """
    try:
        udh_len = int(user_data_hex[:2], 16)
        udh_bytes = bytes.fromhex(user_data_hex[2:2 + udh_len * 2])
        rest = user_data_hex[2 + udh_len * 2:]
        i = 0
        while i < len(udh_bytes):
            ie_id = udh_bytes[i]
            ie_len = udh_bytes[i + 1]
            if ie_id == 0x00 and ie_len == 3:
                return {
                    'ref':   udh_bytes[i + 2],
                    'total': udh_bytes[i + 3],
                    'part':  udh_bytes[i + 4]
                }, rest
            if ie_id == 0x08 and ie_len == 4:
                return {
                    'ref':   (udh_bytes[i + 2] << 8) | udh_bytes[i + 3],
                    'total': udh_bytes[i + 4],
                    'part':  udh_bytes[i + 5]
                }, rest
            i += 2 + ie_len
    except Exception:
        pass
    return None, user_data_hex


def build_submit_pdu(number, text):
    """Build SMS-SUBMIT PDU for sending.
    :param number str: destination phone number
    :param text str: message text
    :return tuple: (pdu_hex_string, tpdu_length_in_bytes)
    """
    smsc = '00'
    tp_mti = 0x11
    tp_mr = '00'
    toa = '91' if number.startswith('+') else '81'
    addr_digits = number.lstrip('+')
    addr_len = '%02X' % len(addr_digits)
    addr_val = number_to_semi_octet(number)
    tp_pid = '00'
    tp_vp = 'AA'  # validity period: 4 days
    if is_gsm7_encodable(text):
        tp_dcs = '00'
        septets, packed = encode_gsm7(text)
        tp_udl = '%02X' % len(septets)
        ud = packed.hex().upper()
    else:
        tp_dcs = '08'  # UCS2
        encoded = bytearray()
        for ch in text:
            cp = ord(ch)
            if cp > 0xFFFF:
                high = 0xD800 + ((cp - 0x10000) >> 10)
                low = 0xDC00 + ((cp - 0x10000) & 0x3FF)
                encoded.append(high >> 8); encoded.append(high & 0xFF)
                encoded.append(low >> 8); encoded.append(low & 0xFF)
            else:
                encoded.append(cp >> 8); encoded.append(cp & 0xFF)
        tp_udl = '%02X' % len(encoded)
        ud = encoded.hex().upper()
    tpdu = '%02X' % tp_mti + tp_mr + addr_len + toa + addr_val + tp_pid + tp_dcs + tp_vp + tp_udl + ud
    return smsc + tpdu, len(tpdu) // 2
