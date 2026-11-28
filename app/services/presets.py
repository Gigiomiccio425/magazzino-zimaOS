"""Modelli pronti (preset) dei componenti più diffusi e riconoscimento del modello da un codice letto.

I preset riempiono il modulo "nuovo componente": nome, categoria, produttore, modello, codice oggetto
(il part number) e caratteristiche. Il riconoscimento prova prima il part number esatto, poi decodifica
gli schemi di sigla più comuni delle RAM (Kingston, Corsair, Crucial, G.Skill, Samsung, SK Hynix):
così anche un modulo non in elenco viene compilato in buona parte. I dati vanno sempre verificati
sull'etichetta del pezzo.
"""
import re
from dataclasses import dataclass, field

RAM_FIELDS = ("Capacita (GB)", "Tipo", "Velocita (MHz)", "Form factor")
# tipo memoria: (marca, linea, part number, generazione, form, GB totali, moduli, MT/s, CL, volt)
RAM = [
    # ---- Kingston ValueRAM DDR (DDR1) ----
    ("Kingston", "ValueRAM", "KVR400X64C3A/512", "DDR", "DIMM", 0.5, 1, 400, 3, 2.6),
    ("Kingston", "ValueRAM", "KVR400X64C3A/1G", "DDR", "DIMM", 1, 1, 400, 3, 2.6),
    ("Kingston", "ValueRAM", "KVR333X64C25/512", "DDR", "DIMM", 0.5, 1, 333, 2.5, 2.5),
    ("Kingston", "ValueRAM", "KVR333X64C25/1G", "DDR", "DIMM", 1, 1, 333, 2.5, 2.5),
    ("Kingston", "ValueRAM", "KVR400X64SC3A/512", "DDR", "SO-DIMM", 0.5, 1, 400, 3, 2.6),
    ("Kingston", "ValueRAM", "KVR400X64SC3A/1G", "DDR", "SO-DIMM", 1, 1, 400, 3, 2.6),
    # ---- Kingston ValueRAM DDR2 ----
    ("Kingston", "ValueRAM", "KVR533D2N4/1G", "DDR2", "DIMM", 1, 1, 533, 4, 1.8),
    ("Kingston", "ValueRAM", "KVR667D2N5/1G", "DDR2", "DIMM", 1, 1, 667, 5, 1.8),
    ("Kingston", "ValueRAM", "KVR667D2N5/2G", "DDR2", "DIMM", 2, 1, 667, 5, 1.8),
    ("Kingston", "ValueRAM", "KVR800D2N6/1G", "DDR2", "DIMM", 1, 1, 800, 6, 1.8),
    ("Kingston", "ValueRAM", "KVR800D2N6/2G", "DDR2", "DIMM", 2, 1, 800, 6, 1.8),
    ("Kingston", "ValueRAM", "KVR667D2S5/1G", "DDR2", "SO-DIMM", 1, 1, 667, 5, 1.8),
    ("Kingston", "ValueRAM", "KVR667D2S5/2G", "DDR2", "SO-DIMM", 2, 1, 667, 5, 1.8),
    ("Kingston", "ValueRAM", "KVR800D2S6/2G", "DDR2", "SO-DIMM", 2, 1, 800, 6, 1.8),
    # ---- Kingston ValueRAM DDR3 ----
    ("Kingston", "ValueRAM", "KVR1333D3N9/2G", "DDR3", "DIMM", 2, 1, 1333, 9, 1.5),
    ("Kingston", "ValueRAM", "KVR1333D3N9/4G", "DDR3", "DIMM", 4, 1, 1333, 9, 1.5),
    ("Kingston", "ValueRAM", "KVR13N9S8/4", "DDR3", "DIMM", 4, 1, 1333, 9, 1.5),
    ("Kingston", "ValueRAM", "KVR16N11/4", "DDR3", "DIMM", 4, 1, 1600, 11, 1.5),
    ("Kingston", "ValueRAM", "KVR16N11S8/4", "DDR3", "DIMM", 4, 1, 1600, 11, 1.5),
    ("Kingston", "ValueRAM", "KVR16N11/8", "DDR3", "DIMM", 8, 1, 1600, 11, 1.5),
    ("Kingston", "ValueRAM", "KVR1333D3S9/4G", "DDR3", "SO-DIMM", 4, 1, 1333, 9, 1.5),
    ("Kingston", "ValueRAM", "KVR16S11S8/4", "DDR3", "SO-DIMM", 4, 1, 1600, 11, 1.5),
    ("Kingston", "ValueRAM", "KVR16S11/8", "DDR3", "SO-DIMM", 8, 1, 1600, 11, 1.5),
    ("Kingston", "ValueRAM", "KVR16LS11/8", "DDR3", "SO-DIMM", 8, 1, 1600, 11, 1.35),
    ("Kingston", "ValueRAM", "KVR16LN11/8", "DDR3", "DIMM", 8, 1, 1600, 11, 1.35),
    # ---- Kingston ValueRAM DDR4 ----
    ("Kingston", "ValueRAM", "KVR21N15S8/8", "DDR4", "DIMM", 8, 1, 2133, 15, 1.2),
    ("Kingston", "ValueRAM", "KVR24N17S8/8", "DDR4", "DIMM", 8, 1, 2400, 17, 1.2),
    ("Kingston", "ValueRAM", "KVR24N17D8/16", "DDR4", "DIMM", 16, 1, 2400, 17, 1.2),
    ("Kingston", "ValueRAM", "KVR26N19S6/4", "DDR4", "DIMM", 4, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR26N19S8/8", "DDR4", "DIMM", 8, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR26N19S8/16", "DDR4", "DIMM", 16, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR26N19D8/16", "DDR4", "DIMM", 16, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR32N22S6/8", "DDR4", "DIMM", 8, 1, 3200, 22, 1.2),
    ("Kingston", "ValueRAM", "KVR32N22S8/8", "DDR4", "DIMM", 8, 1, 3200, 22, 1.2),
    ("Kingston", "ValueRAM", "KVR32N22S8/16", "DDR4", "DIMM", 16, 1, 3200, 22, 1.2),
    ("Kingston", "ValueRAM", "KVR32N22D8/32", "DDR4", "DIMM", 32, 1, 3200, 22, 1.2),
    ("Kingston", "ValueRAM", "KVR21S15S8/8", "DDR4", "SO-DIMM", 8, 1, 2133, 15, 1.2),
    ("Kingston", "ValueRAM", "KVR24S17S8/8", "DDR4", "SO-DIMM", 8, 1, 2400, 17, 1.2),
    ("Kingston", "ValueRAM", "KVR26S19S6/4", "DDR4", "SO-DIMM", 4, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR26S19S8/8", "DDR4", "SO-DIMM", 8, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR26S19S8/16", "DDR4", "SO-DIMM", 16, 1, 2666, 19, 1.2),
    ("Kingston", "ValueRAM", "KVR32S22S6/8", "DDR4", "SO-DIMM", 8, 1, 3200, 22, 1.2),
    ("Kingston", "ValueRAM", "KVR32S22S8/16", "DDR4", "SO-DIMM", 16, 1, 3200, 22, 1.2),
    ("Kingston", "ValueRAM", "KVR32S22D8/32", "DDR4", "SO-DIMM", 32, 1, 3200, 22, 1.2),
    # ---- Kingston ValueRAM DDR5 ----
    ("Kingston", "ValueRAM", "KVR48U40BS6-8", "DDR5", "DIMM", 8, 1, 4800, 40, 1.1),
    ("Kingston", "ValueRAM", "KVR48U40BS8-16", "DDR5", "DIMM", 16, 1, 4800, 40, 1.1),
    ("Kingston", "ValueRAM", "KVR48U40BD8-32", "DDR5", "DIMM", 32, 1, 4800, 40, 1.1),
    ("Kingston", "ValueRAM", "KVR52U42BS8-16", "DDR5", "DIMM", 16, 1, 5200, 42, 1.1),
    ("Kingston", "ValueRAM", "KVR56U46BS8-16", "DDR5", "DIMM", 16, 1, 5600, 46, 1.1),
    ("Kingston", "ValueRAM", "KVR56U46BD8-32", "DDR5", "DIMM", 32, 1, 5600, 46, 1.1),
    ("Kingston", "ValueRAM", "KVR48S40BS6-8", "DDR5", "SO-DIMM", 8, 1, 4800, 40, 1.1),
    ("Kingston", "ValueRAM", "KVR48S40BS8-16", "DDR5", "SO-DIMM", 16, 1, 4800, 40, 1.1),
    ("Kingston", "ValueRAM", "KVR56S46BS8-16", "DDR5", "SO-DIMM", 16, 1, 5600, 46, 1.1),
    ("Kingston", "ValueRAM", "KVR56S46BD8-32", "DDR5", "SO-DIMM", 32, 1, 5600, 46, 1.1),
    # ---- Kingston HyperX / FURY ----
    ("Kingston", "HyperX Fury", "HX316C10F/4", "DDR3", "DIMM", 4, 1, 1600, 10, 1.5),
    ("Kingston", "HyperX Fury", "HX316C10F/8", "DDR3", "DIMM", 8, 1, 1600, 10, 1.5),
    ("Kingston", "HyperX Fury", "HX318C10F/8", "DDR3", "DIMM", 8, 1, 1866, 10, 1.5),
    ("Kingston", "HyperX Fury", "HX426C16FB3/8", "DDR4", "DIMM", 8, 1, 2666, 16, 1.2),
    ("Kingston", "HyperX Fury", "HX426C16FB3/16", "DDR4", "DIMM", 16, 1, 2666, 16, 1.2),
    ("Kingston", "HyperX Fury", "HX432C16FB3/8", "DDR4", "DIMM", 8, 1, 3200, 16, 1.35),
    ("Kingston", "HyperX Fury", "HX432C16FB3/16", "DDR4", "DIMM", 16, 1, 3200, 16, 1.35),
    ("Kingston", "FURY Beast", "KF426C16BB/8", "DDR4", "DIMM", 8, 1, 2666, 16, 1.2),
    ("Kingston", "FURY Beast", "KF432C16BB/8", "DDR4", "DIMM", 8, 1, 3200, 16, 1.35),
    ("Kingston", "FURY Beast", "KF432C16BB/16", "DDR4", "DIMM", 16, 1, 3200, 16, 1.35),
    ("Kingston", "FURY Beast", "KF432C16BBK2/16", "DDR4", "DIMM", 16, 2, 3200, 16, 1.35),
    ("Kingston", "FURY Beast", "KF432C16BBK2/32", "DDR4", "DIMM", 32, 2, 3200, 16, 1.35),
    ("Kingston", "FURY Beast", "KF436C17BB/16", "DDR4", "DIMM", 16, 1, 3600, 17, 1.35),
    ("Kingston", "FURY Impact", "KF432S20IB/16", "DDR4", "SO-DIMM", 16, 1, 3200, 20, 1.2),
    ("Kingston", "FURY Beast", "KF552C40BB-16", "DDR5", "DIMM", 16, 1, 5200, 40, 1.25),
    ("Kingston", "FURY Beast", "KF552C40BBK2-32", "DDR5", "DIMM", 32, 2, 5200, 40, 1.25),
    ("Kingston", "FURY Beast", "KF556C40BB-16", "DDR5", "DIMM", 16, 1, 5600, 40, 1.25),
    ("Kingston", "FURY Beast", "KF556C40BBK2-32", "DDR5", "DIMM", 32, 2, 5600, 40, 1.25),
    ("Kingston", "FURY Beast", "KF560C40BB-16", "DDR5", "DIMM", 16, 1, 6000, 40, 1.35),
    ("Kingston", "FURY Beast", "KF560C40BBK2-32", "DDR5", "DIMM", 32, 2, 6000, 40, 1.35),
    ("Kingston", "FURY Impact", "KF548S38IB-16", "DDR5", "SO-DIMM", 16, 1, 4800, 38, 1.1),
    # ---- Corsair ----
    ("Corsair", "Vengeance", "CMZ8GX3M2A1600C9", "DDR3", "DIMM", 8, 2, 1600, 9, 1.5),
    ("Corsair", "Vengeance", "CMZ16GX3M2A1600C10", "DDR3", "DIMM", 16, 2, 1600, 10, 1.5),
    ("Corsair", "Value Select", "CMSO8GX3M1A1333C9", "DDR3", "SO-DIMM", 8, 1, 1333, 9, 1.5),
    ("Corsair", "Vengeance LPX", "CMK8GX4M1E3200C16", "DDR4", "DIMM", 8, 1, 3200, 16, 1.35),
    ("Corsair", "Vengeance LPX", "CMK16GX4M1E3200C16", "DDR4", "DIMM", 16, 1, 3200, 16, 1.35),
    ("Corsair", "Vengeance LPX", "CMK16GX4M2B3200C16", "DDR4", "DIMM", 16, 2, 3200, 16, 1.35),
    ("Corsair", "Vengeance LPX", "CMK32GX4M2E3200C16", "DDR4", "DIMM", 32, 2, 3200, 16, 1.35),
    ("Corsair", "Vengeance LPX", "CMK16GX4M2D3600C18", "DDR4", "DIMM", 16, 2, 3600, 18, 1.35),
    ("Corsair", "Vengeance RGB Pro", "CMW16GX4M2C3200C16", "DDR4", "DIMM", 16, 2, 3200, 16, 1.35),
    ("Corsair", "Vengeance", "CMSX8GX4M1A2666C18", "DDR4", "SO-DIMM", 8, 1, 2666, 18, 1.2),
    ("Corsair", "Vengeance", "CMSX16GX4M1A2666C18", "DDR4", "SO-DIMM", 16, 1, 2666, 18, 1.2),
    ("Corsair", "Vengeance", "CMK32GX5M2B5200C40", "DDR5", "DIMM", 32, 2, 5200, 40, 1.25),
    ("Corsair", "Vengeance", "CMK32GX5M2B5600C36", "DDR5", "DIMM", 32, 2, 5600, 36, 1.25),
    ("Corsair", "Vengeance", "CMK32GX5M2B6000C30", "DDR5", "DIMM", 32, 2, 6000, 30, 1.4),
    # ---- Crucial ----
    ("Crucial", "Basics", "CT51264BA160B", "DDR3", "DIMM", 4, 1, 1600, 11, 1.35),
    ("Crucial", "Basics", "CT102464BA160B", "DDR3", "DIMM", 8, 1, 1600, 11, 1.35),
    ("Crucial", "", "CT8G4DFS824A", "DDR4", "DIMM", 8, 1, 2400, 17, 1.2),
    ("Crucial", "", "CT8G4DFS832A", "DDR4", "DIMM", 8, 1, 3200, 22, 1.2),
    ("Crucial", "", "CT16G4DFRA32A", "DDR4", "DIMM", 16, 1, 3200, 22, 1.2),
    ("Crucial", "", "CT8G4SFS832A", "DDR4", "SO-DIMM", 8, 1, 3200, 22, 1.2),
    ("Crucial", "", "CT16G4SFRA32A", "DDR4", "SO-DIMM", 16, 1, 3200, 22, 1.2),
    ("Crucial", "Ballistix", "BL8G32C16U4B", "DDR4", "DIMM", 8, 1, 3200, 16, 1.35),
    ("Crucial", "Ballistix", "BL16G32C16U4B", "DDR4", "DIMM", 16, 1, 3200, 16, 1.35),
    ("Crucial", "", "CT16G48C40U5", "DDR5", "DIMM", 16, 1, 4800, 40, 1.1),
    ("Crucial", "", "CT32G48C40U5", "DDR5", "DIMM", 32, 1, 4800, 40, 1.1),
    ("Crucial", "", "CT16G56C46U5", "DDR5", "DIMM", 16, 1, 5600, 46, 1.1),
    ("Crucial", "", "CT16G48C40S5", "DDR5", "SO-DIMM", 16, 1, 4800, 40, 1.1),
    ("Crucial", "", "CT16G56C46S5", "DDR5", "SO-DIMM", 16, 1, 5600, 46, 1.1),
    # ---- G.Skill ----
    ("G.Skill", "Ripjaws X", "F3-12800CL9D-8GBXL", "DDR3", "DIMM", 8, 2, 1600, 9, 1.5),
    ("G.Skill", "Ripjaws V", "F4-3200C16D-16GVKB", "DDR4", "DIMM", 16, 2, 3200, 16, 1.35),
    ("G.Skill", "Ripjaws V", "F4-3200C16D-32GVK", "DDR4", "DIMM", 32, 2, 3200, 16, 1.35),
    ("G.Skill", "Trident Z Neo", "F4-3600C16D-32GTZN", "DDR4", "DIMM", 32, 2, 3600, 16, 1.35),
    ("G.Skill", "Trident Z5 RGB", "F5-6000J3636F16GX2-TZ5RK", "DDR5", "DIMM", 32, 2, 6000, 36, 1.35),
    ("G.Skill", "Flare X5", "F5-6000J3038F16GX2-FX5", "DDR5", "DIMM", 32, 2, 6000, 30, 1.35),
    # ---- Samsung (OEM) ----
    ("Samsung", "", "M378B5173QH0-CK0", "DDR3", "DIMM", 4, 1, 1600, 11, 1.5),
    ("Samsung", "", "M471B5173QH0-YK0", "DDR3", "SO-DIMM", 4, 1, 1600, 11, 1.35),
    ("Samsung", "", "M378A1K43CB2-CTD", "DDR4", "DIMM", 8, 1, 2666, 19, 1.2),
    ("Samsung", "", "M378A2K43CB1-CTD", "DDR4", "DIMM", 16, 1, 2666, 19, 1.2),
    ("Samsung", "", "M471A1K43DB1-CWE", "DDR4", "SO-DIMM", 8, 1, 3200, 22, 1.2),
    ("Samsung", "", "M471A2K43EB1-CWE", "DDR4", "SO-DIMM", 16, 1, 3200, 22, 1.2),
    ("Samsung", "", "M323R2GA3BB0-CQK", "DDR5", "DIMM", 16, 1, 4800, 40, 1.1),
    ("Samsung", "", "M425R2GA3BB0-CQK", "DDR5", "SO-DIMM", 16, 1, 4800, 40, 1.1),
    # ---- SK Hynix (OEM) ----
    ("SK Hynix", "", "HMT451U6BFR8C-PB", "DDR3", "DIMM", 4, 1, 1600, 11, 1.5),
    ("SK Hynix", "", "HMA81GU6CJR8N-VK", "DDR4", "DIMM", 8, 1, 2666, 19, 1.2),
    ("SK Hynix", "", "HMA82GS6DJR8N-XN", "DDR4", "SO-DIMM", 16, 1, 3200, 22, 1.2),
]

# altri componenti molto diffusi: (categoria, marca, linea/nome, part number, caratteristiche)
OTHER = [
    ("SSD", "Samsung", "870 EVO 500 GB", "MZ-77E500B/EU", {"Capacita (GB)": 500, "Interfaccia": "SATA", "Form factor": "2,5\"", "TBW": 300}),
    ("SSD", "Samsung", "870 EVO 1 TB", "MZ-77E1T0B/EU", {"Capacita (GB)": 1000, "Interfaccia": "SATA", "Form factor": "2,5\"", "TBW": 600}),
    ("SSD", "Samsung", "980 PRO 1 TB", "MZ-V8P1T0BW", {"Capacita (GB)": 1000, "Interfaccia": "NVMe PCIe 4.0", "Form factor": "M.2 2280", "TBW": 600}),
    ("SSD", "Samsung", "990 PRO 1 TB", "MZ-V9P1T0BW", {"Capacita (GB)": 1000, "Interfaccia": "NVMe PCIe 4.0", "Form factor": "M.2 2280", "TBW": 600}),
    ("SSD", "Samsung", "990 PRO 2 TB", "MZ-V9P2T0BW", {"Capacita (GB)": 2000, "Interfaccia": "NVMe PCIe 4.0", "Form factor": "M.2 2280", "TBW": 1200}),
    ("SSD", "Kingston", "A400 240 GB", "SA400S37/240G", {"Capacita (GB)": 240, "Interfaccia": "SATA", "Form factor": "2,5\"", "TBW": 80}),
    ("SSD", "Kingston", "A400 480 GB", "SA400S37/480G", {"Capacita (GB)": 480, "Interfaccia": "SATA", "Form factor": "2,5\"", "TBW": 160}),
    ("SSD", "Kingston", "NV2 1 TB", "SNV2S/1000G", {"Capacita (GB)": 1000, "Interfaccia": "NVMe PCIe 4.0", "Form factor": "M.2 2280", "TBW": 320}),
    ("SSD", "Kingston", "KC3000 1 TB", "SKC3000S/1024G", {"Capacita (GB)": 1024, "Interfaccia": "NVMe PCIe 4.0", "Form factor": "M.2 2280", "TBW": 800}),
    ("SSD", "Crucial", "MX500 500 GB", "CT500MX500SSD1", {"Capacita (GB)": 500, "Interfaccia": "SATA", "Form factor": "2,5\"", "TBW": 180}),
    ("SSD", "Crucial", "MX500 1 TB", "CT1000MX500SSD1", {"Capacita (GB)": 1000, "Interfaccia": "SATA", "Form factor": "2,5\"", "TBW": 360}),
    ("SSD", "Crucial", "P3 1 TB", "CT1000P3SSD8", {"Capacita (GB)": 1000, "Interfaccia": "NVMe PCIe 3.0", "Form factor": "M.2 2280", "TBW": 220}),
    ("SSD", "Western Digital", "Blue SN580 1 TB", "WDS100T3B0E", {"Capacita (GB)": 1000, "Interfaccia": "NVMe PCIe 4.0", "Form factor": "M.2 2280", "TBW": 600}),
    ("GPU", "NVIDIA", "GeForce RTX 3060 12 GB", "", {"VRAM (GB)": 12, "Chipset": "GA106", "Tipo memoria": "GDDR6", "Interfaccia": "PCIe 4.0 x16", "TDP": 170}),
    ("GPU", "NVIDIA", "GeForce RTX 3070 8 GB", "", {"VRAM (GB)": 8, "Chipset": "GA104", "Tipo memoria": "GDDR6", "Interfaccia": "PCIe 4.0 x16", "TDP": 220}),
    ("GPU", "NVIDIA", "GeForce RTX 3080 10 GB", "", {"VRAM (GB)": 10, "Chipset": "GA102", "Tipo memoria": "GDDR6X", "Interfaccia": "PCIe 4.0 x16", "TDP": 320}),
    ("GPU", "NVIDIA", "GeForce RTX 4060 8 GB", "", {"VRAM (GB)": 8, "Chipset": "AD107", "Tipo memoria": "GDDR6", "Interfaccia": "PCIe 4.0 x8", "TDP": 115}),
    ("GPU", "NVIDIA", "GeForce RTX 4070 12 GB", "", {"VRAM (GB)": 12, "Chipset": "AD104", "Tipo memoria": "GDDR6X", "Interfaccia": "PCIe 4.0 x16", "TDP": 200}),
    ("GPU", "AMD", "Radeon RX 6600 8 GB", "", {"VRAM (GB)": 8, "Chipset": "Navi 23", "Tipo memoria": "GDDR6", "Interfaccia": "PCIe 4.0 x8", "TDP": 132}),
    ("GPU", "AMD", "Radeon RX 6700 XT 12 GB", "", {"VRAM (GB)": 12, "Chipset": "Navi 22", "Tipo memoria": "GDDR6", "Interfaccia": "PCIe 4.0 x16", "TDP": 230}),
    ("GPU", "AMD", "Radeon RX 7800 XT 16 GB", "", {"VRAM (GB)": 16, "Chipset": "Navi 32", "Tipo memoria": "GDDR6", "Interfaccia": "PCIe 4.0 x16", "TDP": 263}),
]


@dataclass
class Preset:
    id: str
    category: str
    manufacturer: str
    line: str
    part: str
    name: str
    attributes: dict = field(default_factory=dict)
    guessed: bool = False  # True = ricavato dalla sigla, non dall'elenco

    @property
    def label(self) -> str:
        return " · ".join(x for x in [self.name, self.part] if x)

    def as_dict(self) -> dict:
        return {"id": self.id, "category": self.category, "manufacturer": self.manufacturer, "line": self.line,
                "part": self.part, "name": self.name, "label": self.label, "attributes": self.attributes,
                "guessed": self.guessed}


def _gb(value: float) -> str:
    return f"{int(value * 1024)} MB" if value < 1 else f"{value:g} GB"


def ram_type_choice(gen: str, form: str) -> str:
    """Valore del campo "Tipo" della categoria RAM (es. "DDR4" o "SO-DIMM DDR4")."""
    return f"SO-DIMM {gen}" if form == "SO-DIMM" else gen


def _ram_preset(brand, line, part, gen, form, gb, modules, speed, cl, volt, guessed=False) -> Preset:
    gb = int(gb) if float(gb).is_integer() else gb
    kit = f" (kit {modules} × {_gb(gb / modules)})" if modules and modules > 1 else ""
    name = f"RAM {gen} {_gb(gb)} {speed}{' SO-DIMM' if form == 'SO-DIMM' else ''} {brand}{(' ' + line) if line else ''}{kit}"
    attrs = {"Capacita (GB)": gb, "Tipo": ram_type_choice(gen, form), "Velocita (MHz)": speed, "Form factor": form}
    if cl:
        attrs["Latenza (CL)"] = cl
    if volt:
        attrs["Tensione (V)"] = volt
    if modules and modules > 1:
        attrs["Moduli"] = modules
    return Preset(_slug(part or name), "RAM", brand, line, part, " ".join(name.split()), attrs, guessed)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _build() -> list[Preset]:
    out = [_ram_preset(*row) for row in RAM]
    for cat, brand, title, part, attrs in OTHER:
        out.append(Preset(_slug(part or f"{brand}-{title}"), cat, brand, "", part, f"{cat} {brand} {title}", dict(attrs)))
    return out


PRESETS: list[Preset] = _build()
_BY_ID = {p.id: p for p in PRESETS}
_BY_PART = {re.sub(r"[^A-Z0-9]", "", p.part.upper()): p for p in PRESETS if p.part}


def get(preset_id: str) -> Preset | None:
    return _BY_ID.get(preset_id or "")


def search(q: str, limit: int = 30) -> list[Preset]:
    words = [w for w in re.split(r"\s+", (q or "").lower()) if w]
    if not words:
        return PRESETS[:limit]
    keys = [re.sub(r"[^a-z0-9]", "", w) for w in words]
    hits = []
    for p in PRESETS:
        text = " ".join([p.name, p.manufacturer, p.line, p.category]).lower().replace("-", "").replace(".", "")
        tokens = re.findall(r"[a-z0-9]+", text)
        part = re.sub(r"[^a-z0-9]", "", p.part.lower())
        # ogni parola deve iniziare una parola del nome (ddr5 non trova "ddr 512 mb") o stare nella sigla
        if all(k and (any(t.startswith(k) for t in tokens) or (len(k) >= 3 and k in part)) for k in keys):
            hits.append(p)
    return hits[:limit]


# ---------------------------------------------------------------------------
# Riconoscimento dalle sigle (part number) delle RAM
# ---------------------------------------------------------------------------
_KVR_SPEED = {"13": 1333, "16": 1600, "18": 1866, "21": 2133, "24": 2400, "26": 2666, "29": 2933, "32": 3200}


def _speed(code: str) -> int:
    """Velocità dalle due cifre delle sigle: 26 -> 2666, 32 -> 3200, 52 -> 5200."""
    return _KVR_SPEED.get(code, int(code) * 100)


def _decode_ram(part: str) -> Preset | None:
    p = part.upper()
    # Kingston ValueRAM DDR3/DDR4 recenti: KVR26N19S8/8, KVR16LS11/8
    m = re.fullmatch(r"KVR(\d{2})(L?)([NS])(\d{1,2})(?:[SD]\d)?/(\d+)G?", p)
    if m and m.group(1) in _KVR_SPEED:
        speed, cl = _KVR_SPEED[m.group(1)], int(m.group(4))
        gen = "DDR4" if speed >= 2133 and cl >= 15 else "DDR3"
        return _ram_preset("Kingston", "ValueRAM", part, gen, "SO-DIMM" if m.group(3) == "S" else "DIMM",
                           float(m.group(5)), 1, speed, cl, 1.35 if m.group(2) else (1.2 if gen == "DDR4" else 1.5), True)
    # Kingston ValueRAM DDR2/DDR3 vecchie: KVR800D2N6/2G, KVR1333D3S9/4G
    m = re.fullmatch(r"KVR(\d{3,4})D([23])([NSE])(\d+)/(\d+)G", p)
    if m:
        gen = "DDR" + m.group(2)
        return _ram_preset("Kingston", "ValueRAM", part, gen, "SO-DIMM" if m.group(3) == "S" else "DIMM",
                           float(m.group(5)), 1, int(m.group(1)), int(m.group(4)), 1.8 if gen == "DDR2" else 1.5, True)
    # Kingston ValueRAM DDR1: KVR400X64C3A/512
    m = re.fullmatch(r"KVR(\d{3})X64(S?)C(\d+)A?/(\d+)(G?)", p)
    if m:
        gb = float(m.group(4)) if m.group(5) else float(m.group(4)) / 1024
        return _ram_preset("Kingston", "ValueRAM", part, "DDR", "SO-DIMM" if m.group(2) else "DIMM", gb, 1,
                           int(m.group(1)), int(m.group(3)[:1]) if len(m.group(3)) > 1 else int(m.group(3)), 2.6, True)
    # Kingston ValueRAM DDR5: KVR48U40BS8-16
    m = re.fullmatch(r"KVR(\d{2})([US])(\d{2})B[SD]\d-(\d+)", p)
    if m:
        return _ram_preset("Kingston", "ValueRAM", part, "DDR5", "SO-DIMM" if m.group(2) == "S" else "DIMM",
                           float(m.group(4)), 1, int(m.group(1)) * 100, int(m.group(3)), 1.1, True)
    # Kingston FURY e HyperX: KF432C16BB/16, KF552C40BBK2-32, HX426C16FB3/16, KF432S20IB/16
    m = re.fullmatch(r"(KF|HX)([345])(\d{2})([CS])(\d{2})[A-Z0-9]*?(?:K(\d))?[/-](\d+)G?", p)
    if m:
        gen = "DDR" + m.group(2)
        return _ram_preset("Kingston", "FURY" if m.group(1) == "KF" else "HyperX", part, gen,
                           "SO-DIMM" if m.group(4) == "S" else "DIMM", float(m.group(7)), int(m.group(6) or 1),
                           _speed(m.group(3)), int(m.group(5)), None, True)
    # Corsair: CMK16GX4M2B3200C16, CMSX8GX4M1A2666C18, CMK32GX5M2B5600C36
    m = re.fullmatch(r"CM([A-Z]{1,3})(\d+)GX([345])M(\d)[A-Z](\d{4})C(\d{1,2})[A-Z0-9]*", p)
    if m:
        form = "SO-DIMM" if m.group(1).startswith("S") else "DIMM"
        return _ram_preset("Corsair", "", part, "DDR" + m.group(3), form, float(m.group(2)), int(m.group(4)),
                           int(m.group(5)), int(m.group(6)), None, True)
    # Crucial Ballistix: BL8G32C16U4B
    m = re.fullmatch(r"BL(\d+)G(\d{2})C(\d{2})U4[A-Z]", p)
    if m:
        return _ram_preset("Crucial", "Ballistix", part, "DDR4", "DIMM", float(m.group(1)), 1, _speed(m.group(2)),
                           int(m.group(3)), 1.35, True)
    # Crucial DDR5: CT16G48C40U5
    m = re.fullmatch(r"CT(\d+)G(\d{2})C(\d{2})([US])5", p)
    if m:
        return _ram_preset("Crucial", "", part, "DDR5", "SO-DIMM" if m.group(4) == "S" else "DIMM",
                           float(m.group(1)), 1, int(m.group(2)) * 100, int(m.group(3)), 1.1, True)
    # Crucial DDR4/DDR3: CT8G4DFS832A, CT16G4SFRA32A
    m = re.fullmatch(r"CT(\d+)G([34])([DS])F[A-Z0-9]*?(\d{2})A", p)
    if m:
        speed = {"24": 2400, "26": 2666, "29": 2933, "32": 3200, "16": 1600, "13": 1333}.get(m.group(4))
        if speed:
            return _ram_preset("Crucial", "", part, "DDR" + m.group(2), "SO-DIMM" if m.group(3) == "S" else "DIMM",
                               float(m.group(1)), 1, speed, None, None, True)
    # G.Skill: F4-3200C16D-16GVKB, F5-6000J3636F16GX2-TZ5RK
    m = re.fullmatch(r"F([345])-(\d{4})[CJ](\d{2})\d*([SDQ]|F(\d+)GX(\d))-?(?:(\d+)G)?[A-Z0-9-]*", p)
    if m:
        modules = {"S": 1, "D": 2, "Q": 4}.get(m.group(4)[:1], int(m.group(6) or 1))
        total = float(m.group(5)) * modules if m.group(5) else float(m.group(7) or 0)
        if total:
            return _ram_preset("G.Skill", "", part, "DDR" + m.group(1), "DIMM", total, modules,
                               int(m.group(2)), int(m.group(3)), None, True)
    # Samsung e SK Hynix: generazione, formato e velocità dal codice
    m = re.fullmatch(r"M(378|471|323|425)([ABR])[0-9A-Z]+-([A-Z0-9]{3})", p)
    if m:
        gen = {"A": "DDR4", "B": "DDR3", "R": "DDR5"}[m.group(2)]
        speed = {"CK0": 1600, "YK0": 1600, "CH9": 1333, "CPB": 2133, "CRC": 2400, "CTD": 2666, "CVF": 2933,
                 "CWE": 3200, "CQK": 4800, "CWM": 5600}.get(m.group(3))
        if speed:
            form = "SO-DIMM" if m.group(1) in ("471", "425") else "DIMM"
            p_ = _ram_preset("Samsung", "", part, gen, form, 0, 1, speed, None, None, True)
            p_.attributes.pop("Capacita (GB)", None)
            p_.name = f"RAM {gen} {speed}{' SO-DIMM' if form == 'SO-DIMM' else ''} Samsung"
            return p_
    m = re.fullmatch(r"(HMT|HMA|HMCG)\d[0-9A-Z]*?([US])6[0-9A-Z]*-([A-Z]{2})", p)
    if m:
        gen = {"HMT": "DDR3", "HMA": "DDR4", "HMCG": "DDR5"}[m.group(1)]
        speed = {"PB": 1600, "TF": 2133, "UH": 2400, "VK": 2666, "WM": 2933, "XN": 3200}.get(m.group(3))
        if speed:
            form = "SO-DIMM" if m.group(2) == "S" else "DIMM"
            p_ = _ram_preset("SK Hynix", "", part, gen, form, 0, 1, speed, None, None, True)
            p_.attributes.pop("Capacita (GB)", None)
            p_.name = f"RAM {gen} {speed}{' SO-DIMM' if form == 'SO-DIMM' else ''} SK Hynix"
            return p_
    return None


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9/._-]{4,40}")


def recognize(value: str) -> Preset | None:
    """Modello da un codice letto (QR o codice a barre dell'etichetta) o scritto a mano.

    Il codice può contenere altro testo (seriale, lotto, URL): si prova ogni parola.
    """
    text = (value or "").strip()
    if not text:
        return None
    tokens = [text] + _TOKEN.findall(text)
    for tok in tokens:
        hit = _BY_PART.get(re.sub(r"[^A-Z0-9]", "", tok.upper()))
        if hit:
            return hit
    for tok in tokens:
        decoded = _decode_ram(tok.strip().strip(".,;"))
        if decoded:
            return decoded
    return None


def auto_tags(category: str, manufacturer: str, attributes: dict | None) -> list[str]:
    """Tag ricavati dalle specifiche (categoria, marca, tipo, capacità, velocità, formato...)."""
    attrs = attributes or {}
    tags: list[str] = []

    def add(value):
        text = " ".join(str(value or "").split()).lower()[:60]
        if text and text not in tags:
            tags.append(text)

    add(category)
    add(manufacturer)
    tipo = str(attrs.get("Tipo") or "")
    for part in tipo.split():
        add(part)
    for key, suffix in (("Capacita (GB)", "gb"), ("VRAM (GB)", "gb vram")):
        num = attrs.get(key)
        if isinstance(num, (int, float)) and num:
            add(f"{int(num * 1024)}mb" if num < 1 else f"{num:g}{suffix}")
    speed = attrs.get("Velocita (MHz)")
    if isinstance(speed, (int, float)) and speed:
        add(f"{speed:g}")
    for key in ("Form factor", "Interfaccia", "Chipset", "Tipo memoria", "Socket", "Certificazione"):
        add(attrs.get(key))
    return tags
