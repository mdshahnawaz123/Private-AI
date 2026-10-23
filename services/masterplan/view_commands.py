"""Allowlisted, read-only drawing actions; never arbitrary code or data edits."""
import re


def parse_view_command(query):
    q = re.sub(r'\s+', ' ', query.lower()).strip(' .!?')
    q = re.sub(r'^(?:please |can you |could you |in mpd |in masterplan )+', '', q)
    if re.search(r'\b(do not|don\'t|why|how)\b', q):
        return None
    if re.search(r'\bwhat\b', q) and not re.search(r'\b(plot|parcel|\d{5,8})\b', q):
        return None
    if q in ('return to original','go back to original','restore original','back to original','reset colors','reset color','revert to original','revert back to original','revert colors','undo colors'):
        return {'type':'return_to_original'}
    if q in ('save working copy','save as copy','download working copy'):
        return {'type':'save_working_copy'}
    if q in ('show all plots','show all','show all land uses','clear filter','reset filter','unhide all','unhide all plots'):
        return {'type':'isolate_land_use','land_use':None}

    land_use_map = {
        'mixed use':'Mixed Use','mixed-use':'Mixed Use','mixed':'Mixed Use',
        'residential':'Residential','villa':'Residential','villas':'Residential',
        'commercial':'Commercial','retail':'Commercial','office':'Commercial',
        'civic':'Civic','public':'Public Facilities','public facilities':'Public Facilities',
        'hospitality':'Hospitality','hotel':'Hospitality',
        'open space':'Open Space / Park','park':'Open Space / Park','parks':'Open Space / Park',
        'utilities':'Utilities','utility':'Utilities',
        'row':'Roads / ROW','roads':'Roads / ROW','road':'Roads / ROW'
    }
    lu_pattern = r'(mixed use|mixed-use|mixed|residential|villas?|commercial|retail|office|civic|public facilities|public|hospitality|hotel|open space|parks?|utilities|utility|row|roads?)'

    # Isolate / Show ONLY specific land use (e.g. "show me only mixed use", "show me mixed use only", "isolate commercial plots", "only show residential")
    m_iso = re.fullmatch(
        r'(?:(?:show|display|filter|view|isolate|keep)(?: me)?(?: only| just)?|only (?:show|display|keep))(?: the| all)? '
        + lu_pattern + r'(?: plots?| parcels?| land use| area| areas| zone| zones)?(?: only| just)?',
        q
    )
    if m_iso and any(w in q for w in ('only', 'just', 'isolate', 'filter')):
        lu_raw = m_iso.group(1)
        return {'type':'isolate_land_use','land_use':land_use_map.get(lu_raw, lu_raw.title())}

    # Plot details / area lookup (e.g. "find the area of plot 5210766", "area of plot 5210766", "what is the area of plot 5210766")
    colors_list = ('yellow', 'red', 'green', 'blue', 'orange', 'purple', 'cyan', 'pink', 'teal', 'magenta', 'gold', 'white')
    has_any_color = any(c in q for c in colors_list)
    m_plot = re.search(r'(?:find|get|show|what is|tell me)?\s*(?:the\s*)?(area|gfa|far|details?|info)?\s*(?:of\s*|for\s*)?(?:plot\s*|parcel\s*)?(?:p[-_ ]*)?(\d{5,8})\b', q)
    if not has_any_color and m_plot and any(w in q for w in ('area', 'gfa', 'far', 'details', 'info', 'find', 'show', 'tell', 'what', 'plot', 'parcel')):
        metric = m_plot.group(1) or 'area'
        pid = m_plot.group(2)
        return {'type': 'get_plot_details', 'plot_id': f'P-{pid}', 'raw_id': pid, 'metric': metric}

    # Ambiguity detection: recolor without color or target
    if re.search(r'\b(?:recolor|re-color)\b', q) or q in ('change color', 'change the color', 'recolor plots', 'recolor the plots', 'color plots'):
        has_color = any(c in q for c in ('yellow', 'red', 'green', 'blue', 'orange', 'purple', 'cyan', 'pink', 'teal', 'magenta', 'gold', 'white'))
        has_target = any(lu in q for lu in land_use_map.keys()) or re.search(r'\d{5,8}', q) or any(w in q for w in ('sector', 'plots', 'parcels', 'selected', 'active', 'all'))
        if not has_color or not has_target:
            return {
                'type': 'clarification_needed',
                'question': 'Which plots would you like to recolor (e.g. Mixed Use, Residential, Commercial, or specific Plot IDs), and which color should be applied (e.g. yellow, blue, red, green)?'
            }

    colors = 'yellow|red|green|blue|orange|purple|cyan|pink|teal|magenta|gold|white'
    match = re.fullmatch(r'(?:make|change|set|color|colour|ccolor|recolor|re-color) (?:the )?(?:(?:color|colour|ccolor) of )?(?:plot )?(?:p-)?(\d{5,8}) (?:hatch )?(?:color |colour )?(?:to )?('+colors+r')', q)
    if match:
        return {'type':'edit_hatches','plot_ids':['P-'+match[1]],'color':match[2]}

    match = re.fullmatch(
        r'(?:make|change|set|color|colour|ccolor|recolor|re-color) (?:the )?(?:(?:color|colour|ccolor) (?:of |for )?)?(?:all |only )?'
        + lu_pattern + r' (?:plots? |parcels? )?(?:hatch )?(?:color |colour )?(?:to |as |in )?('+colors+r')',
        q
    )
    if match:
        lu_raw = match[1]
        return {'type':'edit_hatches','land_use':land_use_map.get(lu_raw, lu_raw.title()),'color':match[2]}

    # Contextual color change (e.g. "change the color to red", "make it orange", "change color to blue")
    m_ctx_color = re.fullmatch(r'(?:make|change|set|color|colour|ccolor|recolor|re-color) (?:the |its |their |this |selected |active )?(?:plot |plots |parcel |parcels |hatch )?(?:color |colour )?(?:to |as |in )?('+colors+r')', q)
    if m_ctx_color:
        return {'type':'recolor_active','color':m_ctx_color.group(1)}

    match = re.fullmatch(r'(?:make|change|set|color|colour|ccolor|recolor|re-color) (?:the )?(?:(?:color|colour|ccolor) of )?(?:all )?plots? (?:with |for |where )?(gfa|area|far)\s*(?:is\s*)?(less than|less then|<|more than|more then|>|greater than)\s*(\d+[\d,.]*)\s*(?:hatch )?(?:color |colour )?(?:to\s*)?('+colors+r')', q)
    if match:
        field = match[1]
        op = '<' if any(k in match[2] for k in ('less', '<', 'below', 'under')) else '>'
        val = float(match[3].replace(',', ''))
        color = match[4]
        return {'type':'edit_hatches', 'filter_field': field, 'operator': op, 'value': val, 'color': color}
    match = re.fullmatch(r'(hide|show|display|turn off|turn on) (?:all |the )?(text|labels|annotations|cad text|plot labels)', q)
    if match:
        hide = match[1] in ('hide','turn off')
        return {'type':'set_text_mode','mode':'off' if hide else 'all'}
    match = re.fullmatch(r'(?:set |change )?(?:the )?text size (?:to )?(\d+)%?', q)
    if match and 30 <= int(match[1]) <= 180:
        return {'type':'set_text_scale','scale':int(match[1])/100}
    if q in ('fit drawing','fit to drawing','zoom to fit','show whole drawing'):
        return {'type':'fit_view'}
    return None
