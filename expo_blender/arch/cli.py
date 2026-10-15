import argparse
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from .core import extract, read, write, digest, validate_furniture


def check_review(review, approval):
    if approval.get('review_sha256') != digest(review) or not approval.get('reviewer', '').strip():
        raise ValueError('Missing/stale approval; inspect and approve this exact review again')


def main():
    p = argparse.ArgumentParser(description='DXF → validated review → human approval → Blender')
    sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('review')
    r.add_argument('source'); r.add_argument('config'); r.add_argument('--out', required=True)
    r.add_argument('--furniture'); r.add_argument('--ai', action='store_true')
    r.add_argument('--model', default=os.getenv('OPENAI_MODEL'))
    a = sub.add_parser('approve')
    a.add_argument('review'); a.add_argument('--reviewer', required=True)
    a.add_argument('--accept', action='store_true', help='Attest geometry, vertical dimensions, exclusions and furnishing checked')
    b = sub.add_parser('build')
    b.add_argument('review'); b.add_argument('--source', required=True); b.add_argument('--config', required=True)
    b.add_argument('--blender', required=True); b.add_argument('--out', required=True)
    b.add_argument('--samples', type=int, default=128); b.add_argument('--resolution', type=int, default=1200)
    args = p.parse_args()
    if args.command == 'review':
        dest = Path(args.out)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            scene = extract(args.source, read(args.config))
            if args.ai and args.furniture:
                raise ValueError('Choose AI or a furniture JSON file')
            if args.ai:
                if not args.model:
                    raise ValueError('Set OPENAI_MODEL or --model to an available structured-output model')
                from .planner import plan
                items = plan(scene, args.model)
            else:
                items = validate_furniture(scene, read(args.furniture) if args.furniture else [])
            review = {'scene': scene, 'furniture': items, 'requires_approval': [
                'Verify layer meanings and every excluded entity', 'Verify wall height, slab thickness and every sill/head against elevations',
                'Confirm all source openings are represented; gaps are never interpreted as doors',
                'Review furnishing, door approaches, and intended use; no code-compliance claim'],
                'render_policy': 'Open ceiling visualization; no roof/ceiling or door/window assemblies inferred'}
            write(dest/'review.json', review)
            write(dest/'status.json', {'status': 'awaiting_approval', 'review_sha256': digest(review)})
            print(f'Review ready: {dest / "review.json"}')
        except Exception as exc:
            # Old successful review must not appear current after a failed extraction.
            for name in ('review.json', 'approval.json'):
                (dest/name).unlink(missing_ok=True)
            write(dest/'status.json', {'status': 'blocked', 'reason': str(exc)})
            raise
    elif args.command == 'approve':
        if not args.accept or not args.reviewer.strip():
            raise ValueError('Inspect review.json first; --accept and named reviewer are required')
        review = read(args.review)
        write(Path(args.review).with_name('approval.json'), {'review_sha256': digest(review),
              'reviewer': args.reviewer, 'approved_at': datetime.now(timezone.utc).isoformat()})
        print('Approval recorded for this exact review')
    else:
        review = read(args.review)
        check_review(review, read(Path(args.review).with_name('approval.json')))
        current = extract(args.source, read(args.config))
        if digest(current) != digest(review['scene']):
            raise ValueError('Source/config changed; regenerate and approve review')
        validate_furniture(current, review['furniture'])
        if not 1 <= args.samples <= 4096 or not 64 <= args.resolution <= 8192:
            raise ValueError('Render parameters outside supported limits')
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).resolve().parents[1]/'blender'/'build.py'
        cmd = [args.blender, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(script),
               '--', str(Path(args.review).resolve()), str(out), str(args.samples), str(args.resolution)]
        with (out/'blender.log').open('w', encoding='utf-8') as log:
            subprocess.run(cmd, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        for filename in ('model.blend', 'render.png', 'manifest.json'):
            if not (out/filename).is_file():
                raise ValueError(f'Blender did not produce {filename}')
        print(f'Build and render complete: {out}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        sys.exit(2)
