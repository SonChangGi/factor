"""Local integrated research commands; never deploy or alter schedules."""
from pathlib import Path
import json


def add_integrated_commands(subparsers):
    collect = subparsers.add_parser('integrated-collect', help='Freeze free union-universe market inputs')
    collect.add_argument('--output', type=Path, required=True)
    collect.add_argument('--start', default='2010-01-01')
    collect.add_argument('--end')
    run = subparsers.add_parser('integrated-run', help='Run integrated research from a frozen snapshot')
    run.add_argument('--snapshot', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--settings', type=Path)
    run.add_argument('--experiment-project', choices=['momentum', 'best'])
    run.add_argument('--experiment-id')
    amend = subparsers.add_parser('integrated-amend', help='Freeze evidence-backed market amendments')
    amend.add_argument('--snapshot', type=Path, required=True)
    amend.add_argument('--amendments', type=Path, required=True)
    amend.add_argument('--output', type=Path, required=True)
    server = subparsers.add_parser('serve-integrated', help='Serve local integrated research and experiments')
    server.add_argument('--snapshot', type=Path, required=True)
    server.add_argument('--site', type=Path, required=True)
    server.add_argument('--runs', type=Path, required=True)
    server.add_argument('--port', type=int, default=8766)


def dispatch(args):
    from .integrated_data import collect_integrated_market, load_integrated_market
    if args.command == 'integrated-collect':
        market = collect_integrated_market(args.output, args.start, args.end)
        print(json.dumps({'snapshotId': market.metadata['snapshotId'], 'path': str(args.output)}))
    elif args.command == 'integrated-amend':
        from .integrated_data import save_integrated_market
        from .integrated_repairs import amend_market
        market = amend_market(load_integrated_market(args.snapshot), json.loads(args.amendments.read_text()))
        save_integrated_market(market, args.output, compression_level=1)
        print(json.dumps({'snapshotId': market.metadata['snapshotId'], 'path': str(args.output)}))
    elif args.command == 'integrated-run':
        from .integrated_service import execute_run, build_site
        market = load_integrated_market(args.snapshot)
        settings = json.loads(args.settings.read_text()) if args.settings else {}
        if bool(args.experiment_project) != bool(args.experiment_id):
            raise ValueError('Specify both --experiment-project and --experiment-id')
        definition = {'project': args.experiment_project, 'id': args.experiment_id} if args.experiment_id else None
        result = execute_run(market, settings, args.output, experiment_definition=definition)
        build_site(args.output / 'site', result)
        print(json.dumps({'result': str(args.output / 'result.json'), 'site': str(args.output / 'site')}))
    else:
        from .integrated_service import serve
        serve(args.snapshot, args.site, args.runs, args.port)
    return 0
