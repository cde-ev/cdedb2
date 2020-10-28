#!/usr/bin/env python3

import argparse


def handle_one(arg):
    output = []
    infile = open(arg)
    try:
        lines = iter(infile)
        while True:
            line = next(lines).strip()
            if not line.startswith('msgid '):
                output.append(line)
                continue
            message = []
            if line != 'msgid ""':
                message.append(line[7:-1])
            while True:
                recline = next(lines).strip()
                if not recline.startswith('"'):
                    break
                message.append(recline[1:-1].replace(r'\n', '').strip())
            m = ' '.join(message)
            output.append(f'msgid "{m}"')
            output.append(recline)
    except StopIteration:
        infile.close()
        with open(arg, 'w') as outfile:
            outfile.write('\n'.join(output))


def execute(args):
    for arg in args.inputs:
        handle_one(arg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Remove extra whitespace.')
    parser.add_argument('inputs', help="path/to/cdedb.po", nargs='+')
    args = parser.parse_args()
    execute(args)
