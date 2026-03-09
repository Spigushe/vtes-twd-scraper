from ruamel.yaml import YAML
from vtes_scraper.models import Tournament
from vtes_scraper.output.txt import tournament_to_txt

yaml = YAML()
with open("twds/2026/02/12822.yaml") as f:
    data = yaml.load(f)
    t = Tournament(**data)
    print(tournament_to_txt(t))
