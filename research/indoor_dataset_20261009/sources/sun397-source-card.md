---
dataset_info:
  features:
  - name: image
    dtype:
      image:
        mode: RGB
  - name: label
    dtype:
      class_label:
        names:
          '0': /a/abbey
          '1': /a/airplane_cabin
          '2': /a/airport_terminal
          '3': /a/alley
          '4': /a/amphitheater
          '5': /a/amusement_arcade
          '6': /a/amusement_park
          '7': /a/anechoic_chamber
          '8': /a/apartment_building/outdoor
          '9': /a/apse/indoor
          '10': /a/aquarium
          '11': /a/aqueduct
          '12': /a/arch
          '13': /a/archive
          '14': /a/arrival_gate/outdoor
          '15': /a/art_gallery
          '16': /a/art_school
          '17': /a/art_studio
          '18': /a/assembly_line
          '19': /a/athletic_field/outdoor
          '20': /a/atrium/public
          '21': /a/attic
          '22': /a/auditorium
          '23': /a/auto_factory
          '24': /b/badlands
          '25': /b/badminton_court/indoor
          '26': /b/baggage_claim
          '27': /b/bakery/shop
          '28': /b/balcony/exterior
          '29': /b/balcony/interior
          '30': /b/ball_pit
          '31': /b/ballroom
          '32': /b/bamboo_forest
          '33': /b/banquet_hall
          '34': /b/bar
          '35': /b/barn
          '36': /b/barndoor
          '37': /b/baseball_field
          '38': /b/basement
          '39': /b/basilica
          '40': /b/basketball_court/outdoor
          '41': /b/bathroom
          '42': /b/batters_box
          '43': /b/bayou
          '44': /b/bazaar/indoor
          '45': /b/bazaar/outdoor
          '46': /b/beach
          '47': /b/beauty_salon
          '48': /b/bedroom
          '49': /b/berth
          '50': /b/biology_laboratory
          '51': /b/bistro/indoor
          '52': /b/boardwalk
          '53': /b/boat_deck
          '54': /b/boathouse
          '55': /b/bookstore
          '56': /b/booth/indoor
          '57': /b/botanical_garden
          '58': /b/bow_window/indoor
          '59': /b/bow_window/outdoor
          '60': /b/bowling_alley
          '61': /b/boxing_ring
          '62': /b/brewery/indoor
          '63': /b/bridge
          '64': /b/building_facade
          '65': /b/bullring
          '66': /b/burial_chamber
          '67': /b/bus_interior
          '68': /b/butchers_shop
          '69': /b/butte
          '70': /c/cabin/outdoor
          '71': /c/cafeteria
          '72': /c/campsite
          '73': /c/campus
          '74': /c/canal/natural
          '75': /c/canal/urban
          '76': /c/candy_store
          '77': /c/canyon
          '78': /c/car_interior/backseat
          '79': /c/car_interior/frontseat
          '80': /c/carrousel
          '81': /c/casino/indoor
          '82': /c/castle
          '83': /c/catacomb
          '84': /c/cathedral/indoor
          '85': /c/cathedral/outdoor
          '86': /c/cavern/indoor
          '87': /c/cemetery
          '88': /c/chalet
          '89': /c/cheese_factory
          '90': /c/chemistry_lab
          '91': /c/chicken_coop/indoor
          '92': /c/chicken_coop/outdoor
          '93': /c/childs_room
          '94': /c/church/indoor
          '95': /c/church/outdoor
          '96': /c/classroom
          '97': /c/clean_room
          '98': /c/cliff
          '99': /c/cloister/indoor
          '100': /c/closet
          '101': /c/clothing_store
          '102': /c/coast
          '103': /c/cockpit
          '104': /c/coffee_shop
          '105': /c/computer_room
          '106': /c/conference_center
          '107': /c/conference_room
          '108': /c/construction_site
          '109': /c/control_room
          '110': /c/control_tower/outdoor
          '111': /c/corn_field
          '112': /c/corral
          '113': /c/corridor
          '114': /c/cottage_garden
          '115': /c/courthouse
          '116': /c/courtroom
          '117': /c/courtyard
          '118': /c/covered_bridge/exterior
          '119': /c/creek
          '120': /c/crevasse
          '121': /c/crosswalk
          '122': /c/cubicle/office
          '123': /d/dam
          '124': /d/delicatessen
          '125': /d/dentists_office
          '126': /d/desert/sand
          '127': /d/desert/vegetation
          '128': /d/diner/indoor
          '129': /d/diner/outdoor
          '130': /d/dinette/home
          '131': /d/dinette/vehicle
          '132': /d/dining_car
          '133': /d/dining_room
          '134': /d/discotheque
          '135': /d/dock
          '136': /d/doorway/outdoor
          '137': /d/dorm_room
          '138': /d/driveway
          '139': /d/driving_range/outdoor
          '140': /d/drugstore
          '141': /e/electrical_substation
          '142': /e/elevator/door
          '143': /e/elevator/interior
          '144': /e/elevator_shaft
          '145': /e/engine_room
          '146': /e/escalator/indoor
          '147': /e/excavation
          '148': /f/factory/indoor
          '149': /f/fairway
          '150': /f/fastfood_restaurant
          '151': /f/field/cultivated
          '152': /f/field/wild
          '153': /f/fire_escape
          '154': /f/fire_station
          '155': /f/firing_range/indoor
          '156': /f/fishpond
          '157': /f/florist_shop/indoor
          '158': /f/food_court
          '159': /f/forest/broadleaf
          '160': /f/forest/needleleaf
          '161': /f/forest_path
          '162': /f/forest_road
          '163': /f/formal_garden
          '164': /f/fountain
          '165': /g/galley
          '166': /g/game_room
          '167': /g/garage/indoor
          '168': /g/garbage_dump
          '169': /g/gas_station
          '170': /g/gazebo/exterior
          '171': /g/general_store/indoor
          '172': /g/general_store/outdoor
          '173': /g/gift_shop
          '174': /g/golf_course
          '175': /g/greenhouse/indoor
          '176': /g/greenhouse/outdoor
          '177': /g/gymnasium/indoor
          '178': /h/hangar/indoor
          '179': /h/hangar/outdoor
          '180': /h/harbor
          '181': /h/hayfield
          '182': /h/heliport
          '183': /h/herb_garden
          '184': /h/highway
          '185': /h/hill
          '186': /h/home_office
          '187': /h/hospital
          '188': /h/hospital_room
          '189': /h/hot_spring
          '190': /h/hot_tub/outdoor
          '191': /h/hotel/outdoor
          '192': /h/hotel_room
          '193': /h/house
          '194': /h/hunting_lodge/outdoor
          '195': /i/ice_cream_parlor
          '196': /i/ice_floe
          '197': /i/ice_shelf
          '198': /i/ice_skating_rink/indoor
          '199': /i/ice_skating_rink/outdoor
          '200': /i/iceberg
          '201': /i/igloo
          '202': /i/industrial_area
          '203': /i/inn/outdoor
          '204': /i/islet
          '205': /j/jacuzzi/indoor
          '206': /j/jail/indoor
          '207': /j/jail_cell
          '208': /j/jewelry_shop
          '209': /k/kasbah
          '210': /k/kennel/indoor
          '211': /k/kennel/outdoor
          '212': /k/kindergarden_classroom
          '213': /k/kitchen
          '214': /k/kitchenette
          '215': /l/labyrinth/outdoor
          '216': /l/lake/natural
          '217': /l/landfill
          '218': /l/landing_deck
          '219': /l/laundromat
          '220': /l/lecture_room
          '221': /l/library/indoor
          '222': /l/library/outdoor
          '223': /l/lido_deck/outdoor
          '224': /l/lift_bridge
          '225': /l/lighthouse
          '226': /l/limousine_interior
          '227': /l/living_room
          '228': /l/lobby
          '229': /l/lock_chamber
          '230': /l/locker_room
          '231': /m/mansion
          '232': /m/manufactured_home
          '233': /m/market/indoor
          '234': /m/market/outdoor
          '235': /m/marsh
          '236': /m/martial_arts_gym
          '237': /m/mausoleum
          '238': /m/medina
          '239': /m/moat/water
          '240': /m/monastery/outdoor
          '241': /m/mosque/indoor
          '242': /m/mosque/outdoor
          '243': /m/motel
          '244': /m/mountain
          '245': /m/mountain_snowy
          '246': /m/movie_theater/indoor
          '247': /m/museum/indoor
          '248': /m/music_store
          '249': /m/music_studio
          '250': /n/nuclear_power_plant/outdoor
          '251': /n/nursery
          '252': /o/oast_house
          '253': /o/observatory/outdoor
          '254': /o/ocean
          '255': /o/office
          '256': /o/office_building
          '257': /o/oil_refinery/outdoor
          '258': /o/oilrig
          '259': /o/operating_room
          '260': /o/orchard
          '261': /o/outhouse/outdoor
          '262': /p/pagoda
          '263': /p/palace
          '264': /p/pantry
          '265': /p/park
          '266': /p/parking_garage/indoor
          '267': /p/parking_garage/outdoor
          '268': /p/parking_lot
          '269': /p/parlor
          '270': /p/pasture
          '271': /p/patio
          '272': /p/pavilion
          '273': /p/pharmacy
          '274': /p/phone_booth
          '275': /p/physics_laboratory
          '276': /p/picnic_area
          '277': /p/pilothouse/indoor
          '278': /p/planetarium/outdoor
          '279': /p/playground
          '280': /p/playroom
          '281': /p/plaza
          '282': /p/podium/indoor
          '283': /p/podium/outdoor
          '284': /p/pond
          '285': /p/poolroom/establishment
          '286': /p/poolroom/home
          '287': /p/power_plant/outdoor
          '288': /p/promenade_deck
          '289': /p/pub/indoor
          '290': /p/pulpit
          '291': /p/putting_green
          '292': /r/racecourse
          '293': /r/raceway
          '294': /r/raft
          '295': /r/railroad_track
          '296': /r/rainforest
          '297': /r/reception
          '298': /r/recreation_room
          '299': /r/residential_neighborhood
          '300': /r/restaurant
          '301': /r/restaurant_kitchen
          '302': /r/restaurant_patio
          '303': /r/rice_paddy
          '304': /r/riding_arena
          '305': /r/river
          '306': /r/rock_arch
          '307': /r/rope_bridge
          '308': /r/ruin
          '309': /r/runway
          '310': /s/sandbar
          '311': /s/sandbox
          '312': /s/sauna
          '313': /s/schoolhouse
          '314': /s/sea_cliff
          '315': /s/server_room
          '316': /s/shed
          '317': /s/shoe_shop
          '318': /s/shopfront
          '319': /s/shopping_mall/indoor
          '320': /s/shower
          '321': /s/skatepark
          '322': /s/ski_lodge
          '323': /s/ski_resort
          '324': /s/ski_slope
          '325': /s/sky
          '326': /s/skyscraper
          '327': /s/slum
          '328': /s/snowfield
          '329': /s/squash_court
          '330': /s/stable
          '331': /s/stadium/baseball
          '332': /s/stadium/football
          '333': /s/stage/indoor
          '334': /s/staircase
          '335': /s/street
          '336': /s/subway_interior
          '337': /s/subway_station/platform
          '338': /s/supermarket
          '339': /s/sushi_bar
          '340': /s/swamp
          '341': /s/swimming_pool/indoor
          '342': /s/swimming_pool/outdoor
          '343': /s/synagogue/indoor
          '344': /s/synagogue/outdoor
          '345': /t/television_studio
          '346': /t/temple/east_asia
          '347': /t/temple/south_asia
          '348': /t/tennis_court/indoor
          '349': /t/tennis_court/outdoor
          '350': /t/tent/outdoor
          '351': /t/theater/indoor_procenium
          '352': /t/theater/indoor_seats
          '353': /t/thriftshop
          '354': /t/throne_room
          '355': /t/ticket_booth
          '356': /t/toll_plaza
          '357': /t/topiary_garden
          '358': /t/tower
          '359': /t/toyshop
          '360': /t/track/outdoor
          '361': /t/train_railway
          '362': /t/train_station/platform
          '363': /t/tree_farm
          '364': /t/tree_house
          '365': /t/trench
          '366': /u/underwater/coral_reef
          '367': /u/utility_room
          '368': /v/valley
          '369': /v/van_interior
          '370': /v/vegetable_garden
          '371': /v/veranda
          '372': /v/veterinarians_office
          '373': /v/viaduct
          '374': /v/videostore
          '375': /v/village
          '376': /v/vineyard
          '377': /v/volcano
          '378': /v/volleyball_court/indoor
          '379': /v/volleyball_court/outdoor
          '380': /w/waiting_room
          '381': /w/warehouse/indoor
          '382': /w/water_tower
          '383': /w/waterfall/block
          '384': /w/waterfall/fan
          '385': /w/waterfall/plunge
          '386': /w/watering_hole
          '387': /w/wave
          '388': /w/wet_bar
          '389': /w/wheat_field
          '390': /w/wind_farm
          '391': /w/windmill
          '392': /w/wine_cellar/barrel_storage
          '393': /w/wine_cellar/bottle_storage
          '394': /w/wrestling_ring/indoor
          '395': /y/yard
          '396': /y/youth_hostel
  splits:
  - name: train
    num_bytes: 46351432884.22
    num_examples: 108754
  download_size: 39510197247
  dataset_size: 46351432884.22
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
task_categories:
- image-classification
language:
- en
tags:
- princeton
pretty_name: SUN397
size_categories:
- 100K<n<1M
paperswithcode_id: sun397
multilinguality:
- monolingual
annotations_creators:
- expert-generated
---

# Scene UNderstanding 397 — SUN397

[![](https://vision.princeton.edu/projects/2010/SUN/sun_mosaic_logo.jpg)](https://vision.princeton.edu/projects/2010/SUN/)

## Dataset Description

- **Homepage:** [SUN Database: Scene Categorization Benchmark](https://vision.princeton.edu/projects/2010/SUN/)

## Description

Scene categorization is a fundamental problem in computer vision.
However, scene understanding research has been constrained by the limited scope of currently-used databases which do not capture the full variety of scene categories.
Whereas standard databases for object categorization contain hundreds of different classes of objects, the largest available dataset of scene categories contains only 15 classes.
In this paper we propose the extensive Scene UNderstanding (SUN) database that contains 899 categories and 130,519 images.
We use 397 well-sampled categories to evaluate numerous state-of-the-art algorithms for scene recognition and establish new bounds of performance.
We measure human scene classification performance on the SUN database and compare this with computational methods.

## Citations

```bibtex
@inproceedings{5539970,
	title     = {SUN database: Large-scale scene recognition from abbey to zoo},
	author    = {Xiao, Jianxiong and Hays, James and Ehinger, Krista A. and Oliva, Aude and Torralba, Antonio},
	year      = 2010,
	booktitle = {2010 IEEE Computer Society Conference on Computer Vision and Pattern Recognition},
	volume    = {},
	number    = {},
	pages     = {3485--3492},
	doi       = {10.1109/CVPR.2010.5539970},
	keywords  = {Sun;Large-scale systems;Layout;Humans;Image databases;Computer vision;Anthropometry;Bridges;Legged locomotion;Spatial databases}
}
@article{Xiao2014SUNDE,
	title     = {SUN Database: Exploring a Large Collection of Scene Categories},
	author    = {Jianxiong Xiao and Krista A. Ehinger and James Hays and Antonio Torralba and Aude Oliva},
	year      = 2014,
	journal   = {International Journal of Computer Vision},
	volume    = 119,
	pages     = {3--22},
	url       = {https://api.semanticscholar.org/CorpusID:10224573}
}
```