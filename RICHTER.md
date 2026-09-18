```mermaid
  graph LR;
      A-->A1 & A2;
      A-->B
      subgraph InSite
      B-->B1;
      B-->C
      C-->C1;
      end
      A1 & A2 --> O1
      A2 & B1 --> O2
      B1 & C1 --> O3
      B1 & C1 --> O4
      O1 & O2 & O3 & O4 --> O;
      O-->P;

A{
    RECORD STREAM
}
A1{
    .wve and .srm
}
A2{    
    sensorarray/EXPERIMENT.csv
}
B{
    MAKE INSITE PROJECT
}
B1{
    EXPERIMENT/:
    EXPERIMENT.pcf
    optional: sensorarray/EXPERIMENT.csv
    optional: stream/ with .gts and .gwf
    optional: export/EXPERIMENT.csv
}
C{
    TRIGGER EVENTS
}
C1{
    EXPERIMENT/:
    BSF/ with .bif and .bsf
    optional: ESF/ with .esf
    optional: ESF/ with .atf
    optional: export/EXPERIMENT event data.csv
    optional: export/EXPERIMENT instrument data.csv
}
O1{
    insitedata2snuffler.py
    +
    stations_csv2stationxml.py
}
O2{
    insitedata2snuffler.py
    +
    stations_pcf2stationxml.py
}
O3{
    bsf2snuffler.py
    optional: esf2snuffler.py
    optional: events_csv2quakeml.py

}
O4{
    build_esf_catalog_from_esfs.py
}
O{
    Obspy
}
P{
    Pyrocko
}
```