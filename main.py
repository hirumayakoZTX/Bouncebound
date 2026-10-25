"""Start the Bouncebound desktop application."""

import argparse

from src.game import Game


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bouncebound: Familiar Defense")
    parser.add_argument('--audio', action='store_true', help='Enable optional presentation sound cues')
    parser.add_argument('--no-effects', action='store_true', help='Disable transient visual effects')
    args = parser.parse_args(argv)
    Game(audio_enabled=args.audio, effects_enabled=not args.no_effects).run()


if __name__ == "__main__":
    main()
