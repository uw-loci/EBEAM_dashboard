# MKS 902B driver

`MKS902BDriver` owns a 900USB virtual COM port on one worker thread. It
discovers the 902B with `MD?`, reads `BR?` and `U?`, and polls `PR4?` every
500 ms. Valid readings are converted to mbar and published as
`(timestamp, pressure_mbar)` tuples through `data_queue`.

The driver never changes transducer configuration. Background log entries are
queued and must be drained from the Tk thread with `flush_queued_logs()`.
Calling `close()` signals the worker and waits for it; the worker itself closes
the serial connection.
