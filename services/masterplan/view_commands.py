"""Allowlisted, read-only drawing actions; never arbitrary code or data edits."""
import re


def parse_view_command(query):
    q = re.sub(r'\s+', ' ', query.lower()).strip(' .!?')
    q = re.sub(r'^(?:please |can you |could you )', '', q)
    if q in ('return to original','go back to original','restore original','back to original'):
        return {'type':'return_to_original'}
    if q in ('save working copy','save as copy','download working copy'):
        return {'type':'save_working_copy'}
    colors='yellow|red|green|blue|orange|purple'
    match=re.fullmatch(r'(?:make|change|set|color|colour) (?:plot )?(?:p-)?(\d{5,8}) (?:hatch )?(?:color |colour )?(?:to )?('+colors+r')',q)
    if match:
        return {'type':'edit_hatches','plot_ids':['P-'+match[1]],'color':match[2]}
    match=re.fullmatch(r'(?:make|change|set|color|colour) (?:all )?(mixed use|mixed-use|residential|commercial) (?:plots )?(?:to )?('+colors+r')',q)
    if match:
        land_use={'mixed use':'Mixed Use','mixed-use':'Mixed Use','residential':'Residential','commercial':'Commercial'}[match[1]]
        return {'type':'edit_hatches','land_use':land_use,'color':match[2]}
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
