import cutter.sample_cut_tool as sct
import sequencer.sequencer as sequencer
import mixer.mixer as mixer

class Controller:

    def pick_command(self, command = "help"):
        while True:
            command = input(">>>")
            if command == "cut":
                self.cut_samples()
            elif command == "seq":
                self.create_sequence()
            elif command == "mix":
                self.mix_samples(command)
            elif command == "help":
                self.print_help()
            elif command == "exit":
                self.exit()
            else:
                print("Unknown command")

    def cut_samples(self):
        file_path = input("Enter the path to the file: ")
        tool = sct.MP3SampleCutTool(file_path)
        tool.select_cut_points()

    def create_sequence(self):
        seq = sequencer.SequencerController()
        seq.command()

    def mix_samples(self, command):
        # Check if the length is given
        if len(command.split(" ")) > 1:
            # Ensure that the length is a number
            if command.split(" ")[1].isdigit():
                length = int(command.split(" ")[1]) * 1000
        # If length is not given, set it to 60 seconds
        else:
            length = 60000

        mixer.generate_mix("samples/", length)

    def print_help(self):
        print("cut - cut the samples")
        print("seq - create a sequence")
        print("mix - mix the samples")
        print("exit - exit the program")

    def exit(self):
        exit()

