"""Format persisted plot fields without invented filenames or substituted values."""


def plot_answer(plot, current_files):
    names = {f['filename'] for f in current_files}
    sources = [{'source': e['filename'], 'filename': e['filename'],
                'page': e.get('sheet') or e.get('page') or 'Plot Register',
                'row': e.get('row'), 'plot_id': plot.plot_id}
               for e in (getattr(plot, 'provenance', []) or [])
               if e.get('filename') in names]
    answer = (f'### Plot Details: **{plot.plot_id}**\n\n'
              f'- **Plot Area**: {plot.area_sqm:,.1f} m²\n'
              f'- **Permitted GFA**: {plot.permitted_gfa:,.1f} m²\n'
              f'- **Achieved GFA**: {plot.achieved_gfa:,.1f} m²\n'
              f'- **FAR**: {plot.far:.2f}\n'
              f'- **Land Use**: {plot.land_use}\n'
              f'- **Sector**: {plot.sector}\n'
              f'- **Status**: {plot.status.title()}\n')
    if sources:
        answer += '\nSource records: ' + '; '.join(
            f"[SOURCE: {e['filename']} | PAGE {e['page']}]" +
            (f" (row {e['row']})" if e.get('row') is not None else '') for e in sources)
    else:
        answer += ('\nFrom the project masterplan register. Original file provenance was not '
                   'recorded for this row; re-import to attach source citations.')
    return answer, sources
