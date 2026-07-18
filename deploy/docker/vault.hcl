ui = false
disable_mlock = true
api_addr = "http://vault:8200"

storage "file" {
  path = "/vault/state/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}
