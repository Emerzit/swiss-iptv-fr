"""User's Swiss Romandy ordering; channel slots can prefer a Swiss variant."""


def lineup_key(channel, config):
    slots = config.get('lineup', [])
    for index, slot in enumerate(slots):
        if channel['id'] in slot['ids']:
            return index, slot['ids'].index(channel['id']), channel['name'].casefold()
    return len(slots), 0, channel['name'].casefold()


def channel_number(channel_id, config):
    return next((slot.get('number') for slot in config.get('lineup', []) if channel_id in slot['ids']), None)


def ordered_selection(selected, config):
    chosen, consumed = [], set()
    for slot in config.get('lineup', []):
        match = next((cid for cid in slot['ids'] if cid in selected), None)
        if match:
            chosen.append(selected[match])
        consumed.update(slot['ids'])
    chosen += sorted((entry for cid, entry in selected.items() if cid not in consumed),
                     key=lambda entry: entry[0]['name'].casefold())
    return chosen
