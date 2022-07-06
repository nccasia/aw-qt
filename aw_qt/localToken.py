import os

class LocalToken:
    authFile = 'auth.tracker'
    token = ""

    def __init__(self) -> None:
        try:
            tokenFile = open(self.authFile, "r")
            token = tokenFile.read()
            tokenFile.close()
            self.token = token
        except:
            self.token = ""
    
    def set(self, token) -> None:
        try:
            tokenFile = open(self.authFile, "w+")
            tokenFile.write(token)
            tokenFile.close()
        except:
            pass

    def delete(self) -> None:
        if os.path.exists(self.authFile):
            os.remove(self.authFile)
