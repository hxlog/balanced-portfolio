select symbol, source, name, category, adjust_modes, adjust, is_selectable, currency
from bp_index_config
where category = 'stock' and is_deleted = 0;