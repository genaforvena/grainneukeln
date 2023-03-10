
class ChannelConfig:
    def __init__(self, low, high):
        if high == 0:
            high = 1
        if low == 0:
            low = 1
        self.high_pass = high
        self.low_pass = low

    def __str__(self):
        return "Low: " + str(self.low_pass) + "\n" + \
               "High: " + str(self.high_pass) + "\n"


class ChannelsConfig:
    def __init__(self, channels: [ChannelConfig]):
        self.channels = channels

    def __str__(self):
        return "Channels: " + str(self.channels) + "\n"