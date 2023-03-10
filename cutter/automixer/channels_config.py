
class ChannelConfig:
    def __init__(self, high, low):
        if high == 0:
            high = 1
        self.high_pass = high
        self.low_pass = low


class ChannelsConfig:
    def __init__(self, channels: [ChannelConfig]):
        self.channels = channels
