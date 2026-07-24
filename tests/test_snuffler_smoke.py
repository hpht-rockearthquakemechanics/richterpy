import numpy as np
from pyrocko import trace

# Creiamo una traccia finta, leggerissima (solo 1000 punti)
dati_finti = np.sin(np.linspace(0, 10, 1000))
traccia_test = trace.Trace(station='TEST', channel='ZZZ', deltat=0.01, ydata=dati_finti)

print("🚀 Lancio dello Snuffler minimale...")
trace.snuffle([traccia_test])
print("🏁 Fine del processo.")
