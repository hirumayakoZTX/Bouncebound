"""Original, static screen presentation. All navigation and gameplay belong to World."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

import pygame

from src.constants import LOGICAL_SIZE, MAX_BP, WINDOW_TITLE
from src.hud import BACKGROUND, BORDER, TEXT, MUTED, ACCENT, BENEFICIAL, HARMFUL
from src.spells import SPELLS
from src.states import GameState, INSTRUCTION_PAGE_COUNT

if TYPE_CHECKING:
    from src.assets import AssetManager
    from src.world import WorldSnapshot


SCREEN_CACHE_LIMIT = 128
FRAME = (32, 32, 896, 512)
INSTRUCTION_BOUNDS = ((48, 150, 424, 174), (488, 150, 424, 174),
                      (48, 338, 424, 174), (488, 338, 424, 174))
PAUSE_PANEL = (224, 144, 512, 272)
INSTRUCTION_CARDS = (
    (
        ('Movement and aiming', (
            'W / Up Arrow: move up.', 'S / Down Arrow: move down.',
            'Mouse: aim inside the battlefield.', 'Left-click: fire a BP volley.',
        )),
        ('Actions and turns', (
            'One successful shot OR spell per turn.', 'Movement, aiming and selection are free.',
            'Failed casts spend no MP or turn.', 'Enemies act after your animation ends.',
        )),
        ('BP and blue crystals', (
            'BP = orbs per shot; maximum 5.', 'Blue crystals improve future volleys.',
            'Rewards settle after the volley ends.', 'Shooting does not consume BP.',
        )),
        ('Spells and unlocks', (
            '1-8: select an unlocked spell.', 'Space: cast; MP and cooldowns apply.',
            'S1: Fire, Starstorm, Cure, Ward, Reraise.', 'S2 adds Esuna and Levitation.',
            'S3 adds Meteor.',
        )),
    ),
    (
        ('Harmful statuses', (
            'Poison: 3 HP each eligible enemy phase.', 'Bind: vertical movement is blocked.',
            'Doom: countdown to forced knockout.', 'Esuna removes Poison/Bind, not Doom.',
        )),
        ('Protection and revival', (
            'Ward: block one ordinary damage event.', 'Levitation: ignore floor effects.',
            'Reraise: next knockout restores 50 HP.', 'Reraise can be cast once per encounter.',
        )),
        ('Stages and completion', (
            'Defeat required enemies and bosses.', 'Enter after Stage Clear: next stage.',
            'Stage 3 ends in Victory.', 'Enter on Victory: Results.',
        )),
        ('Pause, restart and back', (
            'Escape: pause/resume during gameplay.', 'T: retry Stage 2/3 from Game Over.',
            'R: restart from supported end screens.', 'Returns to Stage 1; no checkpoints.',
            'Escape / Backspace: close this guide.',
        )),
    ),
)

STAGE_COPY = {
    1: ('Learn the ricochet', 'Bounce through enemy lines and link Bomb explosions. '
        'Gather blue crystals to build stronger volleys.', 'Ultros and Typhon'),
    2: ('Read the battlefield', 'New enemy abilities bring Poison, Bind and dangerous floor tiles. '
        'Cleanse harmful effects or protect your next action.', 'Chichu'),
    3: ('Hold the final line', 'Face Doom, enraged enemies and the final confrontation. '
        'Choose your shots and defenses with care.', 'Odin'),
}


class ScreenRenderer:
    """A cached backdrop, persistent fonts, and bounded read-only text surfaces."""

    def __init__(self) -> None:
        self.fonts = {name: pygame.font.Font(None, size) for name, size in
                      (('title', 50), ('heading', 32), ('body', 26), ('small', 23))}
        self._text_cache: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._backdrop = self._make_backdrop()
        self._shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        self._shade.fill((4, 8, 17, 176))

    @staticmethod
    def _make_backdrop() -> pygame.Surface:
        surface = pygame.Surface(LOGICAL_SIZE)
        surface.fill((13, 21, 35))
        # Static stars and stepped columns: original geometry, no external media.
        for x in range(0, 960, 48):
            height = 32 + (x // 48 % 5) * 16
            pygame.draw.rect(surface, (19, 31, 47), (x, 576 - height, 32, height))
        for x, y in ((72, 64), (888, 64), (96, 520), (864, 520)):
            pygame.draw.polygon(surface, BORDER, ((x, y-4), (x+4, y), (x, y+4), (x-4, y)))
        pygame.draw.rect(surface, BORDER, FRAME, width=1)
        pygame.draw.rect(surface, (39, 57, 77), (40, 40, 880, 496), width=1)
        return surface

    def _text(self, screen: pygame.Surface, text: str, position: tuple[int, int], *,
              width: int, font: str = 'body', color: tuple[int, int, int] = TEXT,
              centered: bool = False) -> pygame.Rect:
        """Draw an already wrapped line at its original font size."""
        key = (text, font, color)
        image = self._text_cache.get(key)
        if image is None:
            image = self.fonts[font].render(text, True, color)
            self._text_cache[key] = image
            if len(self._text_cache) > SCREEN_CACHE_LIMIT:
                self._text_cache.popitem(last=False)
        else:
            self._text_cache.move_to_end(key)
        x, y = position
        if centered:
            x += (width - image.get_width()) // 2
        return screen.blit(image, (x, y))

    def _wrap(self, text: str, width: int, font: str = 'body') -> tuple[str, ...]:
        words = text.split()
        lines = ['']
        for word in words:
            candidate = (lines[-1] + ' ' + word).strip()
            if lines[-1] and self.fonts[font].size(candidate)[0] > width:
                lines.append(word)
            else:
                lines[-1] = candidate
        return tuple(lines)

    def _paragraph(self, screen: pygame.Surface, text: str, position: tuple[int, int], *,
                   width: int, font: str = 'body', color: tuple[int, int, int] = MUTED,
                   centered: bool = False) -> int:
        x, y = position
        step = 27 if font == 'body' else 22
        for line in self._wrap(text, width, font):
            self._text(screen, line, (x, y), width=width, font=font, color=color, centered=centered)
            y += step
        return y

    @staticmethod
    def _panel(screen: pygame.Surface, bounds: tuple[int, int, int, int], *,
               color: tuple[int, int, int] = BORDER) -> pygame.Rect:
        rect = pygame.Rect(bounds)
        pygame.draw.rect(screen, BACKGROUND, rect)
        pygame.draw.rect(screen, color, rect, width=1)
        pygame.draw.rect(screen, color, (rect.x + 1, rect.y + 1, 4, 12))
        return rect

    def _hint(self, screen: pygame.Surface, label: str, bounds: tuple[int, int, int, int], *,
              color: tuple[int, int, int] = ACCENT) -> None:
        rect = self._panel(screen, bounds, color=color)
        self._text(screen, label, (rect.x + 12, rect.y + (rect.h - 18) // 2),
                   width=rect.w - 24, font='body', color=color, centered=True)

    def _header(self, screen: pygame.Surface, title: str, eyebrow: str, *, color=ACCENT) -> None:
        screen.blit(self._backdrop, (0, 0))
        self._text(screen, eyebrow, (64, 54), width=832, font='small', color=MUTED, centered=True)
        self._text(screen, title, (64, 86), width=832, font='title', color=color, centered=True)

    def menu(self, screen: pygame.Surface, assets: AssetManager) -> None:
        self._header(screen, WINDOW_TITLE, 'RICOCHET DEFENSE / THREE-STAGE CAMPAIGN')
        self._paragraph(screen, 'Bounce through enemy lines. Protect the defense edge.',
                        (72, 160), width=816, centered=True)
        self._text(screen, 'One main action each turn. Make it count.', (72, 204),
                   width=816, font='small', color=MUTED, centered=True)
        crest = self._panel(screen, (80, 264, 192, 198))
        pygame.draw.polygon(screen, (38, 63, 82), ((176, 282), (244, 350), (176, 418), (108, 350)))
        image = assets.load_image('images/player/guardian.png', native_size=(16, 16), scale=6)
        if image.is_fallback:
            pygame.draw.polygon(screen, BENEFICIAL, ((176, 310), (210, 338), (198, 374),
                                                    (176, 398), (154, 374), (142, 338)), width=3)
            pygame.draw.rect(screen, ACCENT, (168, 340, 16, 16))
        else:
            screen.blit(image.surface, image.surface.get_rect(center=(176, 350)))
        self._text(screen, 'Your guardian', (crest.x + 8, 432), width=176,
                   font='small', color=MUTED, centered=True)
        for label, y in (('Enter: Start Game', 264), ('I: Instructions', 338), ('Escape: Quit', 412)):
            self._hint(screen, label, (304, y, 576, 50))
        self._text(screen, 'Keyboard navigation | Offline play | No audio required', (64, 508),
                   width=832, font='small', color=MUTED, centered=True)

    def instructions(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        self._header(screen, 'Instructions', 'FIELD GUIDE')
        page = snapshot.instructions_page
        self._text(screen, f'Page {page + 1} / {INSTRUCTION_PAGE_COUNT}', (64, 126),
                   width=832, font='small', color=MUTED, centered=True)
        for bounds, (title, paragraphs) in zip(INSTRUCTION_BOUNDS, INSTRUCTION_CARDS[page]):
            rect = self._panel(screen, bounds)
            self._text(screen, title, (rect.x + 16, rect.y + 12), width=rect.w - 32,
                       font='heading', color=ACCENT)
            y = rect.y + 48
            for paragraph in paragraphs:
                y = self._paragraph(screen, paragraph, (rect.x + 16, y),
                                    width=rect.w - 32, font='small', color=TEXT)
        self._text(screen, 'Left / Right: Pages     Escape / Backspace: Back to Menu', (48, 523),
                   width=864, font='small', color=ACCENT, centered=True)

    def intro(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        subtitle, description, bosses = STAGE_COPY[snapshot.stage]
        self._header(screen, f'Stage {snapshot.stage}', 'THE DEFENSE CONTINUES')
        self._text(screen, subtitle, (64, 166), width=832, font='heading', centered=True)
        left = self._panel(screen, (64, 226, 512, 228))
        self._text(screen, 'Your objective', (left.x + 24, left.y + 20), width=464,
                   font='heading', color=ACCENT)
        self._paragraph(screen, description, (left.x + 24, left.y + 64), width=464)
        self._text(screen, f'{snapshot.total_waves} scripted waves', (left.x + 24, left.y + 168),
                   width=464, font='body', color=TEXT)
        self._text(screen, 'Defeat every required enemy.', (left.x + 24, left.y + 196),
                   width=464, font='small', color=MUTED)
        right = self._panel(screen, (592, 226, 304, 228))
        self._text(screen, 'Final encounter' if snapshot.has_boss_wave else 'Encounter goal',
                   (right.x + 20, right.y + 20), width=264, font='heading', color=ACCENT)
        self._paragraph(screen, bosses if snapshot.has_boss_wave else 'Clear all required enemies.',
                        (right.x + 20, right.y + 62), width=264, color=TEXT)
        self._text(screen, 'Unlocked spells', (right.x + 20, right.y + 114), width=264,
                   font='small', color=MUTED)
        names = ', '.join(spell.name.removeprefix('Pom ') for spell in SPELLS.values()
                          if spell.unlock_stage <= snapshot.stage)
        self._paragraph(screen, names, (right.x + 20, right.y + 142), width=264,
                        font='small', color=TEXT)
        self._hint(screen, 'Enter: Continue', (256, 484, 448, 44))

    def pause(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        screen.blit(self._shade, (0, 0))
        rect = self._panel(screen, PAUSE_PANEL, color=ACCENT)
        self._text(screen, 'Paused', (rect.x + 24, rect.y + 24), width=464,
                   font='title', color=ACCENT, centered=True)
        phase = {GameState.PLAYER_AIM: 'Aiming is paused.',
                 GameState.SHOT_ANIMATION: 'Your volley is frozen.',
                 GameState.SPELL_ANIMATION: 'Your spell is frozen.',
                 GameState.TURN_RESOLVE: 'Turn resolution is paused.'}
        self._text(screen, phase.get(snapshot.paused_state, 'Gameplay is paused.'),
                   (rect.x + 24, rect.y + 86), width=464, color=MUTED, centered=True)
        for line, y in (('W/S: Move | Mouse: Aim | Click: Shoot', 266),
                        ('1-8: Select spell | Space: Cast', 294)):
            self._text(screen, line, (rect.x + 24, y), width=464, font='small', centered=True)
        self._hint(screen, 'Escape: Resume', (288, 346, 384, 44))

    def terminal(self, screen: pygame.Surface, snapshot: WorldSnapshot) -> None:
        state = snapshot.state
        if state is GameState.STAGE_CLEAR:
            title, eyebrow, color = 'Stage Clear', 'ENCOUNTER COMPLETE', BENEFICIAL
            message = (f'Stage {snapshot.stage} encounter complete' if snapshot.has_boss_wave
                       else 'Prototype encounter complete')
        elif state is GameState.GAME_OVER:
            title, eyebrow, color = 'Game Over', 'THE DEFENSE HAS ENDED', HARMFUL
            message = snapshot.game_over_reason.value if snapshot.game_over_reason else 'Run ended'
        else:
            title = 'Victory' if state is GameState.VICTORY else 'Results'
            eyebrow, color, message = 'THREE-STAGE CAMPAIGN COMPLETE', ACCENT, 'Campaign complete'
        self._header(screen, title, eyebrow, color=color)
        self._paragraph(screen, message, (96, 166), width=768, color=TEXT, centered=True)
        self._panel(screen, (128, 228, 704, 188))
        self._text(screen, f'Stage {snapshot.stage} | Turn {snapshot.turn_index}', (160, 248),
                   width=480, color=TEXT)
        if state is GameState.RESULTS:
            self._text(screen, 'Score: —', (650, 248), width=150, color=MUTED)
        metrics = (('Health', f'HP {snapshot.hp}/{snapshot.max_hp}'),
                   ('Mana', f'MP {snapshot.mp}/{snapshot.max_mp}'), ('Next volley', f'BP {snapshot.bp}/{MAX_BP}'))
        for index, (label, value) in enumerate(metrics):
            rect = self._panel(screen, (152 + index * 220, 296, 216, 92))
            self._text(screen, label, (rect.x + 16, rect.y + 12), width=184, font='small', color=MUTED)
            self._text(screen, value, (rect.x + 16, rect.y + 44), width=184, font='heading', color=color)
        if state is GameState.STAGE_CLEAR and snapshot.next_stage_available:
            self._hint(screen, 'Enter: Next Stage', (256, 440, 448, 44))
            self._hint(screen, 'R: Restart Run', (256, 496, 448, 40))
        elif state is GameState.VICTORY:
            self._hint(screen, 'Enter: Results', (256, 440, 448, 44))
            self._hint(screen, 'R: Restart Run', (256, 496, 448, 40))
        elif state is GameState.GAME_OVER and snapshot.retry_stage_available:
            retry = self._panel(screen, (112, 446, 360, 82), color=HARMFUL)
            self._text(screen, f'T: Retry Stage {snapshot.stage}',
                       (retry.x + 12, retry.y + 10), width=retry.w - 24,
                       font='body', color=HARMFUL, centered=True)
            self._text(screen, 'Restart this stage from Wave 1',
                       (retry.x + 12, retry.y + 48), width=retry.w - 24,
                       font='small', color=TEXT, centered=True)
            restart = self._panel(screen, (488, 446, 360, 82), color=ACCENT)
            self._text(screen, 'R: Restart Campaign',
                       (restart.x + 12, restart.y + 10), width=restart.w - 24,
                       font='body', color=ACCENT, centered=True)
            self._text(screen, 'Return to Stage 1',
                       (restart.x + 12, restart.y + 48), width=restart.w - 24,
                       font='small', color=TEXT, centered=True)
        else:
            if state is GameState.STAGE_CLEAR:
                self._text(screen, 'No next stage is available.', (128, 438), width=704,
                           font='small', color=MUTED, centered=True)
            self._hint(screen, 'R: Restart Run', (256, 488, 448, 44))

    def draw(self, screen: pygame.Surface, snapshot: WorldSnapshot, assets: AssetManager) -> None:
        if snapshot.state is GameState.MENU:
            self.menu(screen, assets)
        elif snapshot.state is GameState.INSTRUCTIONS:
            self.instructions(screen, snapshot)
        elif snapshot.state is GameState.STAGE_INTRO:
            self.intro(screen, snapshot)
        elif snapshot.state is GameState.PAUSED:
            self.pause(screen, snapshot)
        else:
            self.terminal(screen, snapshot)
